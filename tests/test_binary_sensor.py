"""Tests for the HDCVT HDMI Matrix signal sensors."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant

from custom_components.hdcvt_matrix.const import DOMAIN
from custom_components.hdcvt_matrix.registry import entity_reg

from .conftest import MAC, SetupIntegration, get_state, make_session


def sensor_id(hass: HomeAssistant, key: str) -> str:
    """Resolve a binary sensor by unique id."""
    resolved = entity_reg(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{MAC}_{key}"
    )
    assert resolved is not None
    return resolved


async def test_one_sensor_per_port(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """An 8x8 gets eight input and eight output sensors."""
    await setup_integration(make_session())

    for port in range(1, 9):
        assert hass.states.get(sensor_id(hass, f"input_{port}_signal")) is not None
        assert hass.states.get(sensor_id(hass, f"output_{port}_sink")) is not None


async def test_input_signal_follows_the_device(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Inputs 1-3 have sources in the fixture, 4-8 do not."""
    await setup_integration(make_session())

    assert get_state(hass, sensor_id(hass, "input_1_signal")).state == STATE_ON
    assert get_state(hass, sensor_id(hass, "input_3_signal")).state == STATE_ON
    assert get_state(hass, sensor_id(hass, "input_4_signal")).state == STATE_OFF


async def test_output_sink_follows_the_device(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Outputs 1-3 have displays in the fixture, 4-8 do not."""
    await setup_integration(make_session())

    assert get_state(hass, sensor_id(hass, "output_1_sink")).state == STATE_ON
    assert get_state(hass, sensor_id(hass, "output_8_sink")).state == STATE_OFF


async def test_sensors_are_diagnostic(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """These are read-only facts about cabling, not primary controls."""
    await setup_integration(make_session())

    entry = entity_reg(hass).async_get(sensor_id(hass, "input_1_signal"))
    assert entry is not None
    assert entry.entity_category == EntityCategory.DIAGNOSTIC
