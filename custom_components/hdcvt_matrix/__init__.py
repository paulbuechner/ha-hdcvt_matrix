"""The HDCVT HDMI Matrix integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HdcvtMatrixClient, MatrixAuthError, MatrixError
from .const import DOMAIN, MANUFACTURER, PLATFORMS
from .coordinator import HdcvtMatrixCoordinator
from .registry import device_reg
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

type HdcvtMatrixConfigEntry = ConfigEntry[HdcvtMatrixCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HdcvtMatrixConfigEntry) -> bool:
    """Set up a matrix from a config entry."""
    # Actions are global rather than per entry, so register them once.
    if not hass.services.has_service(DOMAIN, "send_display_command"):
        async_setup_services(hass)

    client = HdcvtMatrixClient(
        entry.data[CONF_HOST],
        async_get_clientsession(hass),
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
    )

    try:
        # The API is sessionless, so credentials are checked here rather than
        # on every poll. A password changed on the device surfaces as reauth.
        await client.async_login()
        info = await client.async_get_info()
    except MatrixAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except MatrixError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = HdcvtMatrixCoordinator(hass, entry, client, info)
    await coordinator.async_config_entry_first_refresh()
    # Loaded before the platforms, so the backup sensor and restore button
    # start with the persisted state rather than flickering into it.
    await coordinator.async_load_preset_backup()
    entry.runtime_data = coordinator

    # Registered explicitly so the device carries its name and identity even if
    # a platform fails to set up.
    device_registry = device_reg(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, info.mac_address)},
        connections={(dr.CONNECTION_NETWORK_MAC, info.mac_address)},
        manufacturer=MANUFACTURER,
        model=info.model,
        name=entry.title,
        sw_version=info.firmware,
        # Matrix web UI is HTTP-only; there is no HTTPS to point at.
        configuration_url=f"http://{client.host}",  # NOSONAR
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: HdcvtMatrixConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
