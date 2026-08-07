"""Tests for the HDCVT HDMI Matrix name fields."""

from __future__ import annotations

from homeassistant.components.text.const import DOMAIN as TEXT_DOMAIN
from homeassistant.components.text.const import SERVICE_SET_VALUE
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.hdcvt_matrix.const import DOMAIN

from .conftest import MAC, SetupIntegration, get_state, make_session


def name_id(hass: HomeAssistant, kind: str, index: int) -> str:
    """Resolve a name field by unique id."""
    resolved = er.async_get(hass).async_get_entity_id(
        "text", DOMAIN, f"{MAC}_{kind}_{index}_name"
    )
    assert resolved is not None
    return resolved


async def test_names_come_from_the_device(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Each field shows what the matrix currently stores."""
    await setup_integration(make_session())

    assert get_state(hass, name_id(hass, "input", 1)).state == "Input1"
    assert get_state(hass, name_id(hass, "output", 3)).state == "Output3"
    assert get_state(hass, name_id(hass, "preset", 1)).state == "Desk PC"


async def test_renaming_an_input(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Input names carry the name first, then the one-based index."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        TEXT_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: name_id(hass, "input", 2), "value": "Apple TV"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set input name"]
    assert calls == [{"comhead": "set input name", "name": "Apple TV", "index": 2}]


async def test_renaming_a_preset_uses_a_different_key_order(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Presets send index first; the firmware is inconsistent about this."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        TEXT_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: name_id(hass, "preset", 4), "value": "Movie night"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "preset name"]
    assert calls == [{"comhead": "preset name", "index": 4, "name": "Movie night"}]


async def test_preset_names_allow_more_characters(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The web UI caps ports at 32 characters and presets at 49."""
    await setup_integration(make_session())

    assert get_state(hass, name_id(hass, "input", 1)).attributes["max"] == 32
    assert get_state(hass, name_id(hass, "preset", 1)).attributes["max"] == 49
