"""Routing and preset selection for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
from .api import HDCP_MODES, SCALER_MODES
from .coordinator import HdcvtMatrixCoordinator
from .entity import HdcvtMatrixEntity

# All writes go through the coordinator, which serialises them.
PARALLEL_UPDATES = 0


# Home Assistant fixes this signature: it awaits the callback and passes `hass`
# whether or not a platform needs either. Neither is ours to change.
async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,  # NOSONAR
    entry: HdcvtMatrixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the preset select and one select per output."""
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [HdcvtMatrixPresetSelect(coordinator)]
    # Port count comes from the device, so a 4x4 gets four of these.
    for output in range(1, coordinator.data.output_count + 1):
        entities.append(HdcvtMatrixOutputSelect(coordinator, output))
        entities.append(HdcvtMatrixHdcpSelect(coordinator, output))
        entities.append(HdcvtMatrixScalerSelect(coordinator, output))
    async_add_entities(entities)


class _OutputModeSelect(HdcvtMatrixEntity, SelectEntity):
    """A select backed by one firmware value per output.

    Firmware values are not contiguous (the scaler has no mode 2), so options
    map by value rather than by list position.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _modes: dict[int, str]

    def __init__(
        self, coordinator: HdcvtMatrixCoordinator, output: int, key: str
    ) -> None:
        """Initialise the select for a one-based output."""
        super().__init__(coordinator, f"output_{output}_{key}")
        self._output = output
        names = coordinator.data.output_names
        self._attr_translation_placeholders = {
            "name": names[output - 1] if output <= len(names) else f"Output {output}"
        }
        self._attr_options = list(self._modes.values())

    def _values(self) -> list[int]:
        """Return the per-output firmware values this select reads."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Output settings mean nothing while the matrix is in standby."""
        return super().available and self.coordinator.data.power

    @property
    def current_option(self) -> str | None:
        """Map the firmware value to an option, or None if unrecognised."""
        values = self._values()
        if self._output > len(values):
            return None
        return self._modes.get(values[self._output - 1])

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
        await self.coordinator.async_set_hdcp_mode(self._output, self._mode_for(option))


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
        await self.coordinator.async_set_scaler_mode(
            self._output, self._mode_for(option)
        )


class HdcvtMatrixOutputSelect(HdcvtMatrixEntity, SelectEntity):
    """Choose which input feeds one output."""

    _attr_translation_key = "output"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, output: int) -> None:
        """Initialise the select for a one-based output."""
        super().__init__(coordinator, f"output_{output}")
        self._output = output
        self._attr_translation_placeholders = {
            "name": self._output_name(coordinator.data.output_names)
        }

    def _output_name(self, names: list[str]) -> str:
        """Return the device's name for this output, or its number."""
        if 1 <= self._output <= len(names) and names[self._output - 1]:
            return names[self._output - 1]
        return f"Output {self._output}"

    @property
    def available(self) -> bool:
        """Routing means nothing while the matrix is in standby."""
        return (
            super().available
            and self.coordinator.data.power
            and self._output <= self.coordinator.data.output_count
        )

    @property
    def options(self) -> list[str]:
        """Input names as stored on the matrix."""
        return list(self.coordinator.data.input_names)

    @property
    def current_option(self) -> str | None:
        """The input currently feeding this output."""
        routes = self.coordinator.data.routes
        names = self.coordinator.data.input_names
        if self._output > len(routes):
            return None
        source = routes[self._output - 1]
        if not 1 <= source <= len(names):
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

        await self.coordinator.async_set_route(self._output, source)


class HdcvtMatrixPresetSelect(HdcvtMatrixEntity, SelectEntity):
    """Recall one of the matrix's stored routing presets."""

    _attr_translation_key = "preset"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the preset select."""
        super().__init__(coordinator, "preset")

    @property
    def available(self) -> bool:
        """Presets mean nothing while the matrix is in standby."""
        return super().available and self.coordinator.data.power

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
