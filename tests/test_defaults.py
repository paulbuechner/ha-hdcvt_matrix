"""What a fresh install creates, and what switching a feature off removes.

An 8x8 can expose around ninety entities. Creating them all and leaving most
disabled still clutters the entity list and the registry, so nothing outside
core routing exists until it is asked for in the options.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.hdcvt_matrix.const import (
    CONF_FEATURES,
    DOMAIN,
    FEATURE_RENAMING,
    FEATURE_SIGNAL_SENSORS,
)

from .conftest import MAC, SetupIntegration, make_session


def _keys(hass: HomeAssistant) -> set[str]:
    """Every registry entry this integration owns, by unique id suffix."""
    registry = er.async_get(hass)
    return {
        entry.unique_id.removeprefix(f"{MAC}_")
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
    }


CORE = {"power", "preset", *(f"output_{output}" for output in range(1, 9))}


async def test_a_fresh_install_creates_only_core_routing(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Power, the eight routing selects and preset recall. Nothing else exists."""
    await setup_integration(make_session(), features=[])

    assert _keys(hass) == CORE


async def test_a_feature_creates_its_entities(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Ticking one group brings in that group and nothing more."""
    await setup_integration(make_session(), features=[FEATURE_SIGNAL_SENSORS])

    keys = _keys(hass)
    assert keys > CORE
    assert "input_1_signal" in keys
    assert "output_1_sink" in keys
    # A neighbouring group stays absent.
    assert "input_1_name" not in keys


async def test_turning_a_feature_off_removes_its_entities(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Unticking must delete the entities, not leave unavailable ghosts behind.

    This is the whole point of pruning: the registry has to match what the
    options currently ask for, including after they shrink.
    """
    session = await setup_integration(make_session(), features=[FEATURE_RENAMING])
    assert "input_1_name" in _keys(hass)

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(entry, options={CONF_FEATURES: []})
    # The options flow reloads for us in production; do it by hand here, since
    # pruning happens as each platform sets up. The reload builds a fresh
    # client, so the fake session has to be in place for it too.
    with patch(
        "custom_components.hdcvt_matrix.async_get_clientsession",
        return_value=session,
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert _keys(hass) == CORE
