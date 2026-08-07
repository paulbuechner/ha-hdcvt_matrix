"""Preset saving for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
from .api import CEC_OUTPUT_POWER_OFF, CEC_OUTPUT_POWER_ON
from .coordinator import HdcvtMatrixCoordinator
from .entity import HdcvtMatrixEntity

PARALLEL_UPDATES = 0


# Home Assistant fixes this signature: it awaits the callback and passes `hass`
# whether or not a platform needs either. Neither is ours to change.
async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,  # NOSONAR
    entry: HdcvtMatrixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up preset save buttons and CEC display power per output."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [
        HdcvtMatrixSavePreset(coordinator, index)
        for index in range(1, len(coordinator.data.preset_names) + 1)
    ]
    for output in range(1, coordinator.data.output_count + 1):
        entities.append(HdcvtMatrixDisplayPower(coordinator, output, on=True))
        entities.append(HdcvtMatrixDisplayPower(coordinator, output, on=False))
    async_add_entities(entities)


class HdcvtMatrixDisplayPower(HdcvtMatrixEntity, ButtonEntity):
    """Power a display on or off over CEC.

    A button rather than a switch because CEC here is one-way: the matrix can
    send the command but cannot report whether the display obeyed, or what
    state it is in.
    """

    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: HdcvtMatrixCoordinator, output: int, *, on: bool
    ) -> None:
        """Initialise the CEC power button for a one-based output."""
        action = "on" if on else "off"
        super().__init__(coordinator, f"output_{output}_display_{action}")
        self._output = output
        self._command = CEC_OUTPUT_POWER_ON if on else CEC_OUTPUT_POWER_OFF
        self._attr_translation_key = f"display_{action}"
        names = coordinator.data.output_names
        self._attr_translation_placeholders = {
            "name": names[output - 1] if output <= len(names) else f"Output {output}"
        }

    @property
    def available(self) -> bool:
        """Follows the matrix, deliberately not the sink sensor.

        A display in standby may drop hotplug detect, which would make the
        button to wake it disappear exactly when it is wanted.
        """
        return super().available and self.coordinator.data.power

    async def async_press(self) -> None:
        """Send the CEC power command to this output's display."""
        await self.coordinator.async_send_output_cec(self._output, self._command)


class HdcvtMatrixSavePreset(HdcvtMatrixEntity, ButtonEntity):
    """Overwrite one preset with the routing currently in effect."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "save_preset"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, index: int) -> None:
        """Initialise the button for a one-based preset slot."""
        super().__init__(coordinator, f"save_preset_{index}")
        self._index = index
        names = coordinator.data.preset_names
        self._attr_translation_placeholders = {
            "name": names[index - 1] if index <= len(names) else f"Preset {index}"
        }

    @property
    def available(self) -> bool:
        """Saving a preset is meaningless while the matrix is in standby."""
        return super().available and self.coordinator.data.power

    async def async_press(self) -> None:
        """Store the current routing into this preset."""
        await self.coordinator.async_save_preset(self._index)
