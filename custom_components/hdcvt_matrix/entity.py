"""Shared entity base for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HdcvtMatrixCoordinator


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
