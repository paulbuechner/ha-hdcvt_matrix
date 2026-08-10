"""Signal detection sensors for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
from .const import FEATURE_PRESET_MANAGEMENT, FEATURE_SIGNAL_SENSORS
from .coordinator import HdcvtMatrixCoordinator
from .entity import HdcvtMatrixEntity, HdcvtMatrixPortEntity
from .features import async_prune, enabled

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
    entities: list[BinarySensorEntity] = []
    if enabled(entry, FEATURE_SIGNAL_SENSORS):
        entities.extend(
            HdcvtMatrixInputSignal(coordinator, port)
            for port in range(1, coordinator.data.input_count + 1)
        )
        entities.extend(
            HdcvtMatrixOutputSink(coordinator, port)
            for port in range(1, coordinator.data.output_count + 1)
        )
    if enabled(entry, FEATURE_PRESET_MANAGEMENT):
        entities.append(HdcvtMatrixPresetBackup(coordinator))
    async_prune(hass, entry, "binary_sensor", (e.unique_id or "" for e in entities))
    async_add_entities(entities)


class HdcvtMatrixPresetBackup(HdcvtMatrixEntity, BinarySensorEntity):
    """Whether the device still matches the stored config backup.

    Trips on the preset names and the per-input EDID ids, both of which
    every poll already carries — a firmware flash resets them together with
    the slots it wipes. Preset contents are only readable over the telnet
    CLI, so they are compared during backup and restore rather than on the
    polling path.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "preset_backup"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the backup drift sensor."""
        super().__init__(coordinator, "preset_backup")

    @property
    def is_on(self) -> bool:
        """True when a backed-up preset or EDID no longer matches."""
        coordinator = self.coordinator
        return bool(coordinator.preset_backup_drift or coordinator.edid_backup_drift)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose what is backed up and what has drifted."""
        coordinator = self.coordinator
        return {
            "backup_saved_at": coordinator.preset_backup_saved_at,
            "backed_up_presets": sorted(coordinator.preset_backup),
            "mismatched_presets": list(coordinator.preset_backup_drift),
            "mismatched_edid_inputs": list(coordinator.edid_backup_drift),
        }


class HdcvtMatrixInputSignal(HdcvtMatrixPortEntity, BinarySensorEntity):
    """Whether a source is detected on one input."""

    _attr_device_class = BinarySensorDeviceClass.PLUG
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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
    _attr_translation_key = "output_sink"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, port: int) -> None:
        """Initialise the sensor for a one-based output."""
        super().__init__(coordinator, f"output_{port}_sink", "output", port)

    @property
    def is_on(self) -> bool | None:
        """True when the matrix reports a sink on this output."""
        return self._value(self.coordinator.data.output_connected)
