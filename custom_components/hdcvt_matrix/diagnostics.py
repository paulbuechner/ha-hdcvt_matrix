"""Diagnostics support for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import HdcvtMatrixConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_HOST,
    "macaddress",
    "ipaddress",
    "gateway",
    "subnet",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # NOSONAR - signature fixed by Home Assistant
    entry: HdcvtMatrixConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "state": asdict(coordinator.data) if coordinator.data else None,
        "active_preset": coordinator.active_preset,
        # Read live rather than reusing the poll, so a bug report carries what
        # the firmware says right now, including the commands the polling path
        # deliberately skips.
        "raw": async_redact_data(
            await coordinator.client.async_get_raw_snapshot(), TO_REDACT
        ),
    }
