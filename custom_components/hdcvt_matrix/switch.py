"""Power control for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
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
    """Set up power and panel switches, plus stream and mute per output."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        HdcvtMatrixPowerSwitch(coordinator),
        HdcvtMatrixPanelLockSwitch(coordinator),
        HdcvtMatrixBeepSwitch(coordinator),
    ]
    for output in range(1, coordinator.data.output_count + 1):
        entities.append(HdcvtMatrixOutputSwitch(coordinator, output))
        entities.append(HdcvtMatrixMuteSwitch(coordinator, output))
        entities.append(HdcvtMatrixArcSwitch(coordinator, output))
    async_add_entities(entities)


class HdcvtMatrixPanelLockSwitch(HdcvtMatrixEntity, SwitchEntity):
    """Lock the physical buttons on the front of the matrix."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "panel_lock"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the panel lock switch."""
        super().__init__(coordinator, "panel_lock")

    @property
    def is_on(self) -> bool:
        """True when the front panel is locked."""
        return self.coordinator.data.panel_locked

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Lock the front panel."""
        await self.coordinator.async_set_panel_locked(locked=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unlock the front panel."""
        await self.coordinator.async_set_panel_locked(locked=False)


class HdcvtMatrixBeepSwitch(HdcvtMatrixEntity, SwitchEntity):
    """The beep the matrix makes on a front panel press."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "beep"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the beeper switch."""
        super().__init__(coordinator, "beep")

    @property
    def is_on(self) -> bool:
        """True when the beeper is enabled."""
        return self.coordinator.data.beep_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the beeper."""
        await self.coordinator.async_set_beep(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Silence the beeper."""
        await self.coordinator.async_set_beep(enabled=False)


class _OutputSwitch(HdcvtMatrixEntity, SwitchEntity):
    """Shared plumbing for the per-output switches."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: HdcvtMatrixCoordinator, output: int, key: str
    ) -> None:
        """Initialise the switch for a one-based output."""
        super().__init__(coordinator, f"output_{output}_{key}")
        self._output = output
        names = coordinator.data.output_names
        self._attr_translation_placeholders = {
            "name": names[output - 1] if output <= len(names) else f"Output {output}"
        }

    @property
    def available(self) -> bool:
        """Output settings mean nothing while the matrix is in standby."""
        return super().available and self.coordinator.data.power


class HdcvtMatrixOutputSwitch(_OutputSwitch):
    """Enable or disable the HDMI stream on one output."""

    _attr_translation_key = "output_stream"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, output: int) -> None:
        """Initialise the stream switch."""
        super().__init__(coordinator, output, "stream")

    @property
    def is_on(self) -> bool | None:
        """True when the output is streaming."""
        enabled = self.coordinator.data.output_enabled
        if self._output > len(enabled):
            return None
        return enabled[self._output - 1]

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the stream on this output."""
        await self.coordinator.async_set_output_enabled(self._output, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the stream on this output."""
        await self.coordinator.async_set_output_enabled(self._output, enabled=False)


class HdcvtMatrixMuteSwitch(_OutputSwitch):
    """Mute or unmute the audio on one output."""

    _attr_translation_key = "output_mute"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, output: int) -> None:
        """Initialise the mute switch."""
        super().__init__(coordinator, output, "mute")

    @property
    def is_on(self) -> bool | None:
        """True when this output's audio is muted."""
        muted = self.coordinator.data.audio_muted
        if self._output > len(muted):
            return None
        return muted[self._output - 1]

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mute this output."""
        await self.coordinator.async_set_audio_muted(self._output, muted=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unmute this output."""
        await self.coordinator.async_set_audio_muted(self._output, muted=False)


class HdcvtMatrixPowerSwitch(HdcvtMatrixEntity, SwitchEntity):
    """Switch the matrix between on and standby."""

    _attr_translation_key = "power"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the power switch."""
        super().__init__(coordinator, "power")

    @property
    def is_on(self) -> bool:
        """Whether the matrix is powered up rather than in standby."""
        return self.coordinator.data.power

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Bring the matrix out of standby."""
        await self.coordinator.async_set_power(on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Put the matrix into standby."""
        await self.coordinator.async_set_power(on=False)


class HdcvtMatrixArcSwitch(_OutputSwitch):
    """Audio Return Channel on one output."""

    _attr_translation_key = "output_arc"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, output: int) -> None:
        """Initialise the ARC switch."""
        super().__init__(coordinator, output, "arc")

    @property
    def is_on(self) -> bool | None:
        """True when ARC is enabled on this output."""
        arc = self.coordinator.data.arc_enabled
        if self._output > len(arc):
            return None
        return arc[self._output - 1]

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable ARC."""
        await self.coordinator.async_set_arc(self._output, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable ARC."""
        await self.coordinator.async_set_arc(self._output, enabled=False)
