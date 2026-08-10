"""Tests for the HDCVT HDMI Matrix preset save buttons."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.components.button.const import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.hdcvt_matrix.api.telnet import (
    CMD_NET_REBOOT,
    MatrixTelnetClient,
)
from custom_components.hdcvt_matrix.const import DOMAIN
from custom_components.hdcvt_matrix.registry import entity_reg

from .conftest import MAC, SetupIntegration, make_session

STANDBY = {"get video status": {"comhead": "get video status", "power": 0}}


def button_id(hass: HomeAssistant, index: int) -> str:
    """Resolve the save button for a one-based preset slot."""
    resolved = entity_reg(hass).async_get_entity_id(
        "button", DOMAIN, f"{MAC}_save_preset_{index}"
    )
    assert resolved is not None
    return resolved


async def test_one_button_per_preset(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Eight preset slots produce eight save buttons."""
    await setup_integration(make_session())

    for index in range(1, 9):
        assert hass.states.get(button_id(hass, index)) is not None


async def test_press_saves_that_slot(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Pressing sends the one-based slot index."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: button_id(hass, 2)},
        blocking=True,
    )

    saves = [r for r in session.requests if r["comhead"] == "preset save"]
    assert saves == [{"comhead": "preset save", "index": 2}]


async def test_device_refusal_surfaces(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A result:0 becomes an error rather than a silent no-op."""
    await setup_integration(
        make_session(overrides={"preset save": {"comhead": "preset save", "result": 0}})
    )
    target = button_id(hass, 1)

    with pytest.raises(HomeAssistantError, match="save preset"):
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: target}, blocking=True
        )


async def test_unavailable_in_standby(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Saving a routing preset is meaningless while the matrix is off."""
    await setup_integration(make_session(overrides=STANDBY))

    assert (
        entity_reg(hass).async_get_entity_id("button", DOMAIN, f"{MAC}_save_preset_1")
        is None
    )


def display_id(hass: HomeAssistant, output: int, action: str) -> str:
    """Resolve a CEC display power button by unique id."""
    resolved = entity_reg(hass).async_get_entity_id(
        "button", DOMAIN, f"{MAC}_output_{output}_display_{action}"
    )
    assert resolved is not None
    return resolved


async def test_display_power_sends_a_port_mask(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """CEC targets a mask over all ports, not a port number."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: display_id(hass, 3, "on")},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "cec command"]
    assert calls == [
        {
            "comhead": "cec command",
            "object": 1,
            "port": [0, 0, 1, 0, 0, 0, 0, 0],
            "index": 0,
        }
    ]


async def test_display_off_uses_the_output_numbering(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Outputs use 0=on and 1=off; inputs number the same actions differently."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: display_id(hass, 1, "off")},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "cec command"]
    assert calls[0]["index"] == 1
    assert calls[0]["port"] == [1, 0, 0, 0, 0, 0, 0, 0]


async def test_display_buttons_ignore_sink_detection(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A display in standby may drop HPD, so the wake button must survive it."""
    await setup_integration(
        make_session(
            overrides={
                "get output status": {
                    "comhead": "get output status",
                    "power": 1,
                    "allconnect": [0] * 8,
                    "allhdcp": [3] * 9,
                    "allscaler": [0] * 9,
                    "allout": [1] * 9,
                    "allaudiomute": [1] * 9,
                }
            }
        )
    )

    state = hass.states.get(display_id(hass, 1, "on"))
    assert state is not None
    assert state.state != "unavailable"


async def test_reboot_sends_the_flag(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Reboot carries a scalar flag, like the other system commands."""
    session = await setup_integration(make_session())

    target = entity_reg(hass).async_get_entity_id("button", DOMAIN, f"{MAC}_reboot")
    assert target is not None

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: target}, blocking=True
    )

    assert [r for r in session.requests if r["comhead"] == "reboot"] == [
        {"comhead": "reboot", "reboot": 1}
    ]


async def test_net_reboot_goes_over_telnet(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The network module restart is the one command with no JSON form."""
    session = await setup_integration(make_session())

    target = entity_reg(hass).async_get_entity_id("button", DOMAIN, f"{MAC}_net_reboot")
    assert target is not None

    with patch.object(
        MatrixTelnetClient, "async_command", new_callable=AsyncMock, return_value=""
    ) as command:
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: target}, blocking=True
        )

    command.assert_awaited_once_with(CMD_NET_REBOOT, tolerate_drop=True)
    # Nothing about it went over HTTP; the session saw only the usual polls.
    assert all("net" not in r["comhead"] for r in session.requests)
