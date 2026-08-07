"""Port and preset naming for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
from .api import MAX_PORT_NAME, MAX_PRESET_NAME
from .coordinator import HdcvtMatrixCoordinator
from .entity import HdcvtMatrixPortEntity

PARALLEL_UPDATES = 0


# Home Assistant fixes this signature: it awaits the callback and passes `hass`
# whether or not a platform needs either. Neither is ours to change.
async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,  # NOSONAR
    entry: HdcvtMatrixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a name field per input, output and preset."""
    coordinator = entry.runtime_data
    data = coordinator.data
    counts = {
        "input": data.input_count,
        "output": data.output_count,
        "preset": len(data.preset_names),
    }
    async_add_entities(
        HdcvtMatrixName(coordinator, kind, index)
        for kind, count in counts.items()
        for index in range(1, count + 1)
    )


class HdcvtMatrixName(HdcvtMatrixPortEntity, TextEntity):
    """The name the matrix stores for one port or preset.

    Renaming here renames the corresponding Home Assistant entities too, since
    every per-port entity takes its name from the device.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: HdcvtMatrixCoordinator, kind: str, index: int
    ) -> None:
        """Initialise the name field for a one-based port or preset."""
        super().__init__(coordinator, f"{kind}_{index}_name", kind, index)
        self._attr_translation_key = f"{kind}_name"
        self._attr_native_max = MAX_PRESET_NAME if kind == "preset" else MAX_PORT_NAME
        # This entity names itself by position, not by the value it holds.
        self._attr_translation_placeholders = {"index": str(index)}

    @property
    def native_value(self) -> str | None:
        """The stored name, or None if the matrix has not reported one."""
        return self._value(self.coordinator.data.names_for(self._kind))

    async def async_set_value(self, value: str) -> None:
        """Store a new name on the matrix."""
        await self.coordinator.async_rename(self._kind, self._port, value)
