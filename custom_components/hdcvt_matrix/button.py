"""Preset saving for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
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
    """Set up a save button per preset slot."""
    coordinator = entry.runtime_data
    async_add_entities(
        HdcvtMatrixSavePreset(coordinator, index)
        for index in range(1, len(coordinator.data.preset_names) + 1)
    )


class HdcvtMatrixSavePreset(HdcvtMatrixEntity, ButtonEntity):
    """Overwrite one preset with the routing currently in effect."""

    _attr_entity_category = EntityCategory.CONFIG
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
