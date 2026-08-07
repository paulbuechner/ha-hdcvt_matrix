"""Port and preset naming for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
from .api import MAX_PORT_NAME, MAX_PRESET_NAME
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
    """Set up a name field per input, output and preset."""
    coordinator = entry.runtime_data
    data = coordinator.data
    entities: list[TextEntity] = [
        HdcvtMatrixName(coordinator, "input", port)
        for port in range(1, data.input_count + 1)
    ]
    entities.extend(
        HdcvtMatrixName(coordinator, "output", port)
        for port in range(1, data.output_count + 1)
    )
    entities.extend(
        HdcvtMatrixName(coordinator, "preset", index)
        for index in range(1, len(data.preset_names) + 1)
    )
    async_add_entities(entities)


class HdcvtMatrixName(HdcvtMatrixEntity, TextEntity):
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
        super().__init__(coordinator, f"{kind}_{index}_name")
        self._kind = kind
        self._index = index
        self._attr_translation_key = f"{kind}_name"
        self._attr_native_max = MAX_PRESET_NAME if kind == "preset" else MAX_PORT_NAME
        self._attr_translation_placeholders = {"index": str(index)}

    def _names(self) -> list[str]:
        """Return the list this entity reads from."""
        return {
            "input": self.coordinator.data.input_names,
            "output": self.coordinator.data.output_names,
            "preset": self.coordinator.data.preset_names,
        }[self._kind]

    @property
    def available(self) -> bool:
        """Naming means nothing while the matrix is in standby."""
        return super().available and self.coordinator.data.power

    @property
    def native_value(self) -> str | None:
        """The stored name, or None if the matrix has not reported one."""
        names = self._names()
        if self._index > len(names):
            return None
        return names[self._index - 1]

    async def async_set_value(self, value: str) -> None:
        """Store a new name on the matrix."""
        await self.coordinator.async_rename(self._kind, self._index, value)
