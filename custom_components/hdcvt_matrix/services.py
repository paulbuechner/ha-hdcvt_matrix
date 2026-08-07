"""Actions for sending arbitrary CEC commands.

The matrix can relay 19 CEC commands to a source device and 6 to a display.
Exposing those as entities would mean ~200 buttons on an 8x8, so the long tail
lives here instead; the common ones (display power, volume) stay as buttons.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .api import CEC_INPUT_COMMANDS, CEC_OUTPUT_COMMANDS
from .const import DOMAIN
from .coordinator import HdcvtMatrixCoordinator

SERVICE_SEND_DISPLAY_COMMAND = "send_display_command"
SERVICE_SEND_SOURCE_COMMAND = "send_source_command"

ATTR_PORT = "port"
ATTR_COMMAND = "command"

# The firmware tops out at 8 either way; the coordinator sizes the mask from
# what the device actually reports.
MAX_PORT = 8


def _schema(commands: dict[str, int]) -> vol.Schema:
    """Build the call schema for one direction."""
    return vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): cv.string,
            vol.Required(ATTR_PORT): vol.All(int, vol.Range(min=1, max=MAX_PORT)),
            vol.Required(ATTR_COMMAND): vol.In(sorted(commands)),
        }
    )


def _coordinator_for(hass: HomeAssistant, device_id: str) -> HdcvtMatrixCoordinator:
    """Resolve a targeted device to its loaded coordinator."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"No device with id {device_id}")

    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            if entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(f"{entry.title} is not loaded")
            coordinator: HdcvtMatrixCoordinator = entry.runtime_data
            return coordinator

    raise ServiceValidationError(f"{device.name} is not an HDCVT matrix")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the CEC actions once, for all config entries."""

    async def send_display_command(call: ServiceCall) -> None:
        """Relay a CEC command to the display on an output."""
        coordinator = _coordinator_for(call.hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_send_output_cec(
            call.data[ATTR_PORT], CEC_OUTPUT_COMMANDS[call.data[ATTR_COMMAND]]
        )

    async def send_source_command(call: ServiceCall) -> None:
        """Relay a CEC command to the device on an input."""
        coordinator = _coordinator_for(call.hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_send_input_cec(
            call.data[ATTR_PORT], CEC_INPUT_COMMANDS[call.data[ATTR_COMMAND]]
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_DISPLAY_COMMAND,
        send_display_command,
        schema=_schema(CEC_OUTPUT_COMMANDS),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_SOURCE_COMMAND,
        send_source_command,
        schema=_schema(CEC_INPUT_COMMANDS),
    )
