"""Signal detection sensors for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
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
    """Set up a signal sensor per input and a sink sensor per output."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        HdcvtMatrixInputSignal(coordinator, port)
        for port in range(1, coordinator.data.input_count + 1)
    ]
    entities.extend(
        HdcvtMatrixOutputSink(coordinator, port)
        for port in range(1, coordinator.data.output_count + 1)
    )
    async_add_entities(entities)


class HdcvtMatrixInputSignal(HdcvtMatrixPortEntity, BinarySensorEntity):
    """Whether a source is detected on one input."""

    _attr_device_class = BinarySensorDeviceClass.PLUG
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "input_signal"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, port: int) -> None:
        """Initialise the sensor for a one-based input."""
        super().__init__(coordinator, f"input_{port}_signal", "input", port)

    @property
    def is_on(self) -> bool | None:
        """True when the matrix reports a source on this input."""
        return self._value(self.coordinator.data.input_active)


class HdcvtMatrixOutputSink(HdcvtMatrixPortEntity, BinarySensorEntity):
    """Whether a display is detected on one output."""

    _attr_device_class = BinarySensorDeviceClass.PLUG
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "output_sink"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, port: int) -> None:
        """Initialise the sensor for a one-based output."""
        super().__init__(coordinator, f"output_{port}_sink", "output", port)

    @property
    def is_on(self) -> bool | None:
        """True when the matrix reports a sink on this output."""
        return self._value(self.coordinator.data.output_connected)
