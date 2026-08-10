"""Routing and preset selection for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import HdcvtMatrixConfigEntry
from .api import (
    BAUD_RATES,
    EDID_PROFILES,
    EXT_AUDIO_MODE_MATRIX,
    EXT_AUDIO_MODES,
    HDCP_MODES,
    LCD_ON_TIMES,
    SCALER_MODES,
)
from .const import (
    FEATURE_EDID,
    FEATURE_EXT_AUDIO,
    FEATURE_SYSTEM,
    FEATURE_VIDEO_SETTINGS,
)
from .coordinator import HdcvtMatrixCoordinator
from .entity import HdcvtMatrixEntity, HdcvtMatrixPortEntity
from .features import async_prune, enabled

# All writes go through the coordinator, which serialises them.
PARALLEL_UPDATES = 0


# Home Assistant fixes this signature: it awaits the callback and passes `hass`
# whether or not a platform needs either. Neither is ours to change.
async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,  # NOSONAR
    entry: HdcvtMatrixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up routing, presets and whichever optional selects are switched on."""
    coordinator = entry.runtime_data
    data = coordinator.data

    # Core: routing and preset recall, always present.
    entities: list[SelectEntity] = [HdcvtMatrixPresetSelect(coordinator)]
    # Port count comes from the device, so a 4x4 gets four of these.
    entities.extend(
        HdcvtMatrixOutputSelect(coordinator, output)
        for output in range(1, data.output_count + 1)
    )

    if enabled(entry, FEATURE_VIDEO_SETTINGS):
        for output in range(1, data.output_count + 1):
            entities.append(HdcvtMatrixHdcpSelect(coordinator, output))
            entities.append(HdcvtMatrixScalerSelect(coordinator, output))

    if enabled(entry, FEATURE_EDID):
        entities.extend(
            HdcvtMatrixEdidSelect(coordinator, source)
            for source in range(1, data.input_count + 1)
        )

    if enabled(entry, FEATURE_EXT_AUDIO):
        entities.append(HdcvtMatrixExtAudioModeSelect(coordinator))
        entities.extend(
            HdcvtMatrixExtAudioSelect(coordinator, output)
            for output in range(1, len(data.ext_audio_output_names) + 1)
        )

    if enabled(entry, FEATURE_SYSTEM):
        entities.append(HdcvtMatrixBaudRateSelect(coordinator))
        entities.append(HdcvtMatrixLcdOnTimeSelect(coordinator))

    async_prune(hass, entry, "select", (e.unique_id or "" for e in entities))
    async_add_entities(entities)


class _OutputModeSelect(HdcvtMatrixPortEntity, SelectEntity):
    """A select backed by one firmware value per output.

    Firmware values do not all start at zero (HDCP and the baud rates start
    at 1), so options map by value rather than by list position.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _modes: dict[int, str]

    def __init__(
        self, coordinator: HdcvtMatrixCoordinator, output: int, key: str
    ) -> None:
        """Initialise the select for a one-based output."""
        super().__init__(coordinator, f"output_{output}_{key}", "output", output)
        self._attr_options = list(self._modes.values())

    def _values(self) -> list[int]:
        """Return the per-output firmware values this select reads."""
        raise NotImplementedError

    @property
    def current_option(self) -> str | None:
        """Map the firmware value to an option, or None if unrecognised."""
        value = self._value(self._values())
        return None if value is None else self._modes.get(value)

    def _mode_for(self, option: str) -> int:
        """Map an option back to its firmware value."""
        for value, name in self._modes.items():
            if name == option:
                return value
        raise ServiceValidationError(f"{option!r} is not a valid mode")


class HdcvtMatrixHdcpSelect(_OutputModeSelect):
    """HDCP mode for one output."""

    _attr_translation_key = "output_hdcp"
    _modes = HDCP_MODES

    def __init__(self, coordinator: HdcvtMatrixCoordinator, output: int) -> None:
        """Initialise the HDCP select."""
        super().__init__(coordinator, output, "hdcp")

    def _values(self) -> list[int]:
        return self.coordinator.data.hdcp_modes

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen HDCP mode."""
        await self.coordinator.async_set_hdcp_mode(self._port, self._mode_for(option))


class HdcvtMatrixScalerSelect(_OutputModeSelect):
    """Scaler mode for one output."""

    _attr_translation_key = "output_scaler"
    _modes = SCALER_MODES

    def __init__(self, coordinator: HdcvtMatrixCoordinator, output: int) -> None:
        """Initialise the scaler select."""
        super().__init__(coordinator, output, "scaler")

    def _values(self) -> list[int]:
        return self.coordinator.data.scaler_modes

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen scaler mode."""
        await self.coordinator.async_set_scaler_mode(self._port, self._mode_for(option))


class HdcvtMatrixOutputSelect(HdcvtMatrixPortEntity, SelectEntity):
    """Choose which input feeds one output."""

    _attr_translation_key = "output"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, output: int) -> None:
        """Initialise the select for a one-based output."""
        super().__init__(coordinator, f"output_{output}", "output", output)

    @property
    def options(self) -> list[str]:
        """Input names as stored on the matrix."""
        return list(self.coordinator.data.input_names)

    @property
    def current_option(self) -> str | None:
        """The input currently feeding this output."""
        source = self._value(self.coordinator.data.routes)
        names = self.coordinator.data.input_names
        if source is None or not 1 <= source <= len(names):
            return None
        return names[source - 1]

    async def async_select_option(self, option: str) -> None:
        """Route the named input to this output."""
        names = self.coordinator.data.input_names
        try:
            source = names.index(option) + 1
        except ValueError as err:
            raise ServiceValidationError(
                f"{option!r} is not an input on this matrix"
            ) from err

        await self.coordinator.async_set_route(self._port, source)


class HdcvtMatrixPresetSelect(HdcvtMatrixEntity, RestoreEntity, SelectEntity):
    """Recall one of the matrix's stored routing presets."""

    _attr_translation_key = "preset"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the preset select."""
        super().__init__(coordinator, "preset")

    async def async_added_to_hass(self) -> None:
        """Carry the last applied preset across a restart.

        The firmware cannot report which preset is active, so our own record is
        the only one there is, and it lives in memory. Without restoring it the
        select read unknown after every Home Assistant restart, integration
        reload, and options change.
        """
        await super().async_added_to_hass()
        if self.coordinator.active_preset is not None:
            return

        last = await self.async_get_last_state()
        if last is None:
            return
        names = self.coordinator.data.preset_names
        if last.state in names:
            self.coordinator.active_preset = names.index(last.state) + 1

    @property
    def options(self) -> list[str]:
        """Preset names as stored on the matrix."""
        return list(self.coordinator.data.preset_names)

    @property
    def current_option(self) -> str | None:
        """The preset we last applied, or None if we have never applied one.

        The firmware does not report an active preset, so anything else here
        would be a guess. Recalling a preset also does not stop someone routing
        an individual output afterwards, which would leave this stale.
        """
        index = self.coordinator.active_preset
        names = self.coordinator.data.preset_names
        if index is None or not 1 <= index <= len(names):
            return None
        return names[index - 1]

    async def async_select_option(self, option: str) -> None:
        """Recall the named preset."""
        names = self.coordinator.data.preset_names
        try:
            index = names.index(option) + 1
        except ValueError as err:
            raise ServiceValidationError(
                f"{option!r} is not a preset on this matrix"
            ) from err

        await self.coordinator.async_apply_preset(index)
        self.async_write_ha_state()


class HdcvtMatrixEdidSelect(HdcvtMatrixPortEntity, SelectEntity):
    """EDID profile advertised to the source on one input.

    Options are the firmware's own labels rather than translation keys: they
    are technical identifiers like "4K60(444),2.0CH" that read the same in
    every language.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "input_edid"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, source: int) -> None:
        """Initialise the EDID select for a one-based input."""
        super().__init__(coordinator, f"input_{source}_edid", "input", source)
        self._attr_options = list(EDID_PROFILES.values())

    @property
    def current_option(self) -> str | None:
        """Map the firmware id to a label, or None if unrecognised."""
        edid = self._value(self.coordinator.data.input_edids)
        return None if edid is None else EDID_PROFILES.get(edid)

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen EDID profile."""
        for profile, label in EDID_PROFILES.items():
            if label == option:
                await self.coordinator.async_set_edid(self._port, profile)
                return
        raise ServiceValidationError(f"{option!r} is not a known EDID profile")


class HdcvtMatrixExtAudioModeSelect(HdcvtMatrixEntity, SelectEntity):
    """How the de-embedded audio outputs are driven."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "ext_audio_mode"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the audio mode select."""
        super().__init__(coordinator, "ext_audio_mode")
        self._attr_options = list(EXT_AUDIO_MODES.values())

    @property
    def current_option(self) -> str | None:
        """Map the firmware mode to an option."""
        return EXT_AUDIO_MODES.get(self.coordinator.data.ext_audio_mode)

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen audio mode."""
        for mode, name in EXT_AUDIO_MODES.items():
            if name == option:
                await self.coordinator.async_set_ext_audio_mode(mode)
                return
        raise ServiceValidationError(f"{option!r} is not a valid audio mode")


class HdcvtMatrixExtAudioSelect(HdcvtMatrixPortEntity, SelectEntity):
    """Which input feeds one de-embedded audio output.

    Only meaningful in matrix mode: in the two bind modes the audio follows a
    video port and the matrix ignores routing sent here.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "ext_audio_output"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, output: int) -> None:
        """Initialise the audio routing select for a one-based output."""
        super().__init__(coordinator, f"ext_audio_{output}", "ext_audio", output)

    @property
    def available(self) -> bool:
        """Unavailable outside matrix mode, where routing does nothing."""
        return (
            super().available
            and self.coordinator.data.ext_audio_mode == EXT_AUDIO_MODE_MATRIX
        )

    @property
    def options(self) -> list[str]:
        """Input names as stored on the matrix."""
        return list(self.coordinator.data.input_names)

    @property
    def current_option(self) -> str | None:
        """The input currently feeding this audio output."""
        source = self._value(self.coordinator.data.ext_audio_routes)
        names = self.coordinator.data.input_names
        if source is None or not 1 <= source <= len(names):
            return None
        return names[source - 1]

    async def async_select_option(self, option: str) -> None:
        """Route the named input to this audio output."""
        names = self.coordinator.data.input_names
        try:
            source = names.index(option) + 1
        except ValueError as err:
            raise ServiceValidationError(
                f"{option!r} is not an input on this matrix"
            ) from err

        await self.coordinator.async_set_ext_audio_route(self._port, source)


class _SystemSelect(HdcvtMatrixEntity, SelectEntity):
    """A select backed by one scalar in get system status."""

    _attr_entity_category = EntityCategory.CONFIG
    _values: dict[int, str]

    def __init__(self, coordinator: HdcvtMatrixCoordinator, key: str) -> None:
        """Initialise the select."""
        super().__init__(coordinator, key)
        self._attr_options = list(self._values.values())

    def _current(self) -> int:
        """Return the firmware value this select reads."""
        raise NotImplementedError

    @property
    def current_option(self) -> str | None:
        """Map the firmware value to an option, or None if unrecognised."""
        return self._values.get(self._current())

    def _value_for(self, option: str) -> int:
        """Map an option back to its firmware value."""
        for value, name in self._values.items():
            if name == option:
                return value
        raise ServiceValidationError(f"{option!r} is not a valid setting")


class HdcvtMatrixBaudRateSelect(_SystemSelect):
    """RS-232 rate on the serial control port."""

    _attr_translation_key = "baud_rate"
    _values = BAUD_RATES

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the baud rate select."""
        super().__init__(coordinator, "baud_rate")

    def _current(self) -> int:
        return self.coordinator.data.baud_rate

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen baud rate."""
        await self.coordinator.async_set_baud_rate(self._value_for(option))


class HdcvtMatrixLcdOnTimeSelect(_SystemSelect):
    """How long the front panel backlight stays on."""

    _attr_translation_key = "lcd_on_time"
    _values = LCD_ON_TIMES

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the LCD timeout select."""
        super().__init__(coordinator, "lcd_on_time")

    def _current(self) -> int:
        return self.coordinator.data.lcd_on_time

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen timeout."""
        await self.coordinator.async_set_lcd_on_time(self._value_for(option))
