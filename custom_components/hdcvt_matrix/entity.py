"""Shared entity bases for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from typing import TypeVar

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HdcvtMatrixCoordinator

_T = TypeVar("_T")

# Fallback labels, for when the device reports fewer names than ports.
_PORT_LABELS = {
    "input": "Input",
    "output": "Output",
    "preset": "Preset",
    "ext_audio": "Audio",
}


class HdcvtMatrixEntity(CoordinatorEntity[HdcvtMatrixCoordinator]):
    """Base entity tying every platform to the one matrix device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HdcvtMatrixCoordinator, key: str) -> None:
        """Initialise the entity and bind it to the matrix device."""
        super().__init__(coordinator)
        info = coordinator.info
        self._attr_unique_id = f"{info.mac_address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.mac_address)},
            connections={(CONNECTION_NETWORK_MAC, info.mac_address)},
            manufacturer=MANUFACTURER,
            model=info.model,
            sw_version=info.firmware,
            # Matrix web UI is HTTP-only; there is no HTTPS to point at.
            configuration_url=f"http://{coordinator.client.host}",  # NOSONAR
        )

    # Deliberately no availability override. A matrix in standby is still
    # reachable and still remembers its routing, so entities keep their values
    # and only the power switch changes. Marking them unavailable was both
    # wrong and noisy: it flipped every entity at once on each power change.


class HdcvtMatrixPortEntity(HdcvtMatrixEntity):
    """An entity bound to one one-based input, output or preset.

    Carries the two things every per-port entity needs: a display name taken
    from the device, and a bounds-checked read of the matching array. The
    firmware sizes those arrays itself, so a shorter-than-expected reply reads
    as unknown rather than raising.
    """

    def __init__(
        self,
        coordinator: HdcvtMatrixCoordinator,
        key: str,
        kind: str,
        port: int,
    ) -> None:
        """Initialise the entity for a one-based port of the given kind."""
        super().__init__(coordinator, key)
        self._kind = kind
        self._port = port
        self._attr_translation_placeholders = {"name": self._port_name()}

    def _port_name(self) -> str:
        """Return the device's name for this port, or a positional fallback."""
        names = self.coordinator.data.names_for(self._kind)
        if self._port <= len(names) and names[self._port - 1]:
            return names[self._port - 1]
        return f"{_PORT_LABELS[self._kind]} {self._port}"

    def _value(self, values: list[_T]) -> _T | None:
        """Return this port's entry, or None if the device reported fewer."""
        if self._port > len(values):
            return None
        return values[self._port - 1]
