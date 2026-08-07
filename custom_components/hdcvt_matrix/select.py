"""Routing and preset selection for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
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
    """Set up the preset select and one select per output."""
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [HdcvtMatrixPresetSelect(coordinator)]
    # Port count comes from the device, so a 4x4 gets four of these.
    entities.extend(
        HdcvtMatrixOutputSelect(coordinator, output)
        for output in range(1, coordinator.data.output_count + 1)
    )
    async_add_entities(entities)


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
