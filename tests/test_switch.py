"""Tests for the HDCVT HDMI Matrix power switch."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.switch.const import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.hdcvt_matrix.const import DOMAIN

from .conftest import MAC, FakeSession, SetupIntegration, get_state, make_session

STANDBY = {
    "get video status": {"comhead": "get video status", "power": 0},
}


def _power_calls(session: FakeSession) -> list[dict[str, Any]]:
    """Only the power commands, ignoring the refresh reads that follow."""
    return [r for r in session.requests if r["comhead"] == "set poweronoff"]


def switch_id(hass: HomeAssistant) -> str:
    """Resolve the power switch by unique id."""
    resolved = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{MAC}_power")
    assert resolved is not None
    return resolved


def select_id(hass: HomeAssistant) -> str:
    """Resolve the preset select by unique id."""
    resolved = er.async_get(hass).async_get_entity_id("select", DOMAIN, f"{MAC}_preset")
    assert resolved is not None
    return resolved


async def test_reports_powered_on(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A matrix reporting power:1 shows as on."""
    await setup_integration(make_session())

    assert get_state(hass, switch_id(hass)).state == STATE_ON


async def test_turn_off_sends_zero(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Turning off sends power:0."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: switch_id(hass)},
        blocking=True,
    )

    assert _power_calls(session) == [{"comhead": "set poweronoff", "power": 0}]


async def test_turn_on_sends_one(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Turning on sends power:1."""
    session = await setup_integration(make_session(overrides=STANDBY))

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: switch_id(hass)},
        blocking=True,
    )

    assert _power_calls(session) == [{"comhead": "set poweronoff", "power": 1}]


async def test_state_updates_before_the_device_settles(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The matrix is slow to respond, so the switch reflects the new state at once."""
    await setup_integration(make_session())

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: switch_id(hass)},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert get_state(hass, switch_id(hass)).state == STATE_OFF


async def test_standby_keeps_the_switch_usable(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A standby reply with no port names must not knock out the power control."""
    await setup_integration(make_session(overrides=STANDBY))

    assert get_state(hass, switch_id(hass)).state == STATE_OFF


async def test_standby_makes_the_preset_select_unavailable(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Recalling a preset is meaningless while the matrix is off."""
    await setup_integration(make_session(overrides=STANDBY))

    assert get_state(hass, select_id(hass)).state == STATE_UNAVAILABLE


async def test_device_refusal_surfaces(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A result:0 becomes an error rather than a silent no-op."""
    await setup_integration(
        make_session(
            overrides={"set poweronoff": {"comhead": "set poweronoff", "result": 0}}
        )
    )

    target = switch_id(hass)

    with pytest.raises(HomeAssistantError, match="switch the matrix"):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: target},
            blocking=True,
        )

    assert get_state(hass, target).state == STATE_ON


def output_switch_id(hass: HomeAssistant, output: int, key: str) -> str:
    """Resolve a per-output switch by unique id."""
    resolved = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{MAC}_output_{output}_{key}"
    )
    assert resolved is not None
    return resolved


async def test_output_stream_reflects_the_device(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The fixture reports every output enabled."""
    await setup_integration(make_session())

    assert get_state(hass, output_switch_id(hass, 1, "stream")).state == STATE_ON


async def test_output_stream_toggle_sends_one_based_output(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Disabling output 4 sends out:[4, 0]."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: output_switch_id(hass, 4, "stream")},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "tx stream"]
    assert calls == [{"comhead": "tx stream", "out": [4, 0]}]


async def test_audio_mute_toggle(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Unmuting output 2 sends mute:[2, 0]."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: output_switch_id(hass, 2, "mute")},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set output audio mute"]
    assert calls == [{"comhead": "set output audio mute", "mute": [2, 0]}]


async def test_output_switches_are_config_category(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Per-output plumbing is configuration, not a primary control."""
    await setup_integration(make_session())

    entry = er.async_get(hass).async_get(output_switch_id(hass, 1, "stream"))
    assert entry is not None
    assert entry.entity_category == EntityCategory.CONFIG


def panel_id(hass: HomeAssistant, key: str) -> str:
    """Resolve a front panel switch by unique id."""
    resolved = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{MAC}_{key}")
    assert resolved is not None
    return resolved


async def test_panel_lock_reflects_the_device(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The fixture reports the panel unlocked and the beeper off."""
    await setup_integration(make_session())

    assert get_state(hass, panel_id(hass, "panel_lock")).state == STATE_OFF
    assert get_state(hass, panel_id(hass, "beep")).state == STATE_OFF


async def test_panel_lock_sends_a_scalar_not_an_array(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Unlike the per-output commands, lock takes a bare int."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: panel_id(hass, "panel_lock")},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set panel lock"]
    assert calls == [{"comhead": "set panel lock", "lock": 1}]


async def test_beep_sends_a_scalar(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Same shape for the beeper."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: panel_id(hass, "beep")},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set beep"]
    assert calls == [{"comhead": "set beep", "beep": 1}]


async def test_arc_toggle(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """ARC is off in the fixture; enabling output 5 sends arc:[5, 1]."""
    session = await setup_integration(make_session())

    assert get_state(hass, output_switch_id(hass, 5, "arc")).state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: output_switch_id(hass, 5, "arc")},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set arc"]
    assert calls == [{"comhead": "set arc", "arc": [5, 1]}]


async def test_ext_audio_uses_its_own_port_names(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The audio outputs are named separately from the video outputs.

    Both lists are called alloutputname, in different replies, so reading the
    wrong one is easy and invisible while they happen to match.
    """
    await setup_integration(make_session())

    target = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{MAC}_ext_audio_1_out"
    )
    assert target is not None
    name = get_state(hass, target).attributes["friendly_name"]
    assert "Audio1" in name
    assert "Output1" not in name
