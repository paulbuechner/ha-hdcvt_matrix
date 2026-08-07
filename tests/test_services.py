"""Tests for the CEC relay actions."""

from __future__ import annotations

from typing import Any

import pytest
import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from custom_components.hdcvt_matrix.const import DOMAIN

from .conftest import MAC, FakeSession, SetupIntegration, make_session

DISPLAY = "send_display_command"
SOURCE = "send_source_command"


def matrix_device_id(hass: HomeAssistant) -> str:
    """Return the device id of the configured matrix."""
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, MAC)})
    assert device is not None
    return device.id


def _cec(session: FakeSession) -> list[dict[str, Any]]:
    """Return only the CEC calls."""
    return [r for r in session.requests if r["comhead"] == "cec command"]


async def test_display_command_targets_an_output(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Object 1 is an output, and the port becomes a mask."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        DOMAIN,
        DISPLAY,
        {
            ATTR_DEVICE_ID: matrix_device_id(hass),
            "port": 2,
            "command": "volume_up",
        },
        blocking=True,
    )

    assert _cec(session) == [
        {
            "comhead": "cec command",
            "object": 1,
            "port": [0, 1, 0, 0, 0, 0, 0, 0],
            "index": 4,
        }
    ]


async def test_source_command_targets_an_input(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Object 0 is an input, and play is 11 on that side."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        DOMAIN,
        SOURCE,
        {ATTR_DEVICE_ID: matrix_device_id(hass), "port": 1, "command": "play"},
        blocking=True,
    )

    assert _cec(session) == [
        {
            "comhead": "cec command",
            "object": 0,
            "port": [1, 0, 0, 0, 0, 0, 0, 0],
            "index": 11,
        }
    ]


async def test_power_is_numbered_differently_per_direction(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Outputs use 0 for power on, inputs use 1. Same word, different wire."""
    session = await setup_integration(make_session())
    device_id = matrix_device_id(hass)

    await hass.services.async_call(
        DOMAIN,
        DISPLAY,
        {ATTR_DEVICE_ID: device_id, "port": 1, "command": "power_on"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SOURCE,
        {ATTR_DEVICE_ID: device_id, "port": 1, "command": "power_on"},
        blocking=True,
    )

    assert [call["index"] for call in _cec(session)] == [0, 1]


async def test_display_rejects_a_source_only_command(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A display cannot be told to fast forward; the schema refuses it."""
    session = await setup_integration(make_session())

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            DISPLAY,
            {
                ATTR_DEVICE_ID: matrix_device_id(hass),
                "port": 1,
                "command": "fast_forward",
            },
            blocking=True,
        )

    assert _cec(session) == []


async def test_unknown_device_is_rejected(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Targeting something that is not a matrix fails loudly."""
    await setup_integration(make_session())

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            DISPLAY,
            {ATTR_DEVICE_ID: "does-not-exist", "port": 1, "command": "power_on"},
            blocking=True,
        )
