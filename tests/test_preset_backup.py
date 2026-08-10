"""Tests for the preset backup, drift warning and restore flow."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.components.button.const import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.hdcvt_matrix.api.telnet import MatrixTelnetClient
from custom_components.hdcvt_matrix.const import DOMAIN
from custom_components.hdcvt_matrix.coordinator import HdcvtMatrixCoordinator
from custom_components.hdcvt_matrix.registry import entity_reg

from .conftest import (
    DEVICE_RESPONSES,
    MAC,
    SetupIntegration,
    get_state,
    make_session,
)

# What the device holds in this file's scenario: one saved scene on slot 1.
SLOT_ROUTES = [2, 2, 2, 2, 2, 2, 2, 2]


def telnet_presets(contents: dict[int, list[int]]) -> Any:
    """Answer ``r preset z!`` like the CLI: routes for saved slots, none else."""

    def reply(command: str, **_: Any) -> str:
        slot = int(command.split()[2].rstrip("!"))
        if slot in contents:
            return "\n".join(
                f"output{output}->input{source}"
                for output, source in enumerate(contents[slot], start=1)
            )
        return f"preset {slot} is none,please save a preset"

    return reply


def button(hass: HomeAssistant, key: str) -> str:
    """Resolve one of the backup buttons by unique id."""
    resolved = entity_reg(hass).async_get_entity_id("button", DOMAIN, f"{MAC}_{key}")
    assert resolved is not None
    return resolved


def sensor(hass: HomeAssistant) -> str:
    """Resolve the drift sensor by unique id."""
    resolved = entity_reg(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{MAC}_preset_backup"
    )
    assert resolved is not None
    return resolved


def coordinator_of(hass: HomeAssistant) -> HdcvtMatrixCoordinator:
    """Return the single entry's coordinator."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    coordinator: HdcvtMatrixCoordinator = entry.runtime_data
    return coordinator


def stored_backup(hass: HomeAssistant, hass_storage: dict[str, Any]) -> dict[str, Any]:
    """Return the persisted backup for the single entry."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    data: dict[str, Any] = hass_storage[f"{DOMAIN}.preset_backup_{entry.entry_id}"][
        "data"
    ]
    return data


async def test_backup_snapshots_saved_slots(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_storage: dict[str, Any],
) -> None:
    """The button stores every saved slot with its polled name."""
    await setup_integration(make_session())

    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "backup_presets")},
            blocking=True,
        )

    data = stored_backup(hass, hass_storage)
    assert data["presets"] == {"1": {"name": "Desk PC", "routes": SLOT_ROUTES}}
    # The EDID selections come along for free: they are in the polled state.
    assert data["input_edids"] == {
        **{str(source): 28 for source in range(1, 7)},
        "7": 10,
        "8": 10,
    }
    assert get_state(hass, sensor(hass)).state == "off"


async def test_backup_refuses_an_empty_device(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_storage: dict[str, Any],
) -> None:
    """A wiped device must not overwrite the one good backup."""
    await setup_integration(make_session())

    with (
        patch.object(
            MatrixTelnetClient,
            "async_command",
            new_callable=AsyncMock,
            side_effect=telnet_presets({}),
        ),
        pytest.raises(HomeAssistantError, match="no saved presets"),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "backup_presets")},
            blocking=True,
        )


async def test_name_drift_trips_the_sensor(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A firmware wipe resets preset names, and the next poll notices."""
    video: dict[str, Any] = {
        **DEVICE_RESPONSES["get video status"],
        "allname": ["Desk PC", *[f"Preset{i}" for i in range(2, 9)]],
    }
    await setup_integration(make_session(overrides={"get video status": video}))

    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "backup_presets")},
            blocking=True,
        )
    assert get_state(hass, sensor(hass)).state == "off"

    # The wipe: names fall back to the factory default.
    video["allname"] = [f"Preset{i}" for i in range(1, 9)]
    await coordinator_of(hass).async_refresh()
    await hass.async_block_till_done()

    state = get_state(hass, sensor(hass))
    assert state.state == "on"
    assert state.attributes["mismatched_presets"] == [1]


async def test_restore_rebuilds_the_slots(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Restore applies each slot, saves it, renames it, and puts routing back."""
    video: dict[str, Any] = {
        **DEVICE_RESPONSES["get video status"],
        "allname": ["Desk PC", *[f"Preset{i}" for i in range(2, 9)]],
    }
    session = await setup_integration(
        make_session(overrides={"get video status": video})
    )

    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "backup_presets")},
            blocking=True,
        )

    video["allname"] = [f"Preset{i}" for i in range(1, 9)]
    await coordinator_of(hass).async_refresh()
    await hass.async_block_till_done()
    assert get_state(hass, sensor(hass)).state == "on"

    session.requests.clear()
    # The restore reads the slots back to confirm they took.
    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "restore_presets")},
            blocking=True,
        )
    # The rename inside the restore updated the fake device's names, so the
    # confirming poll agrees on its own.
    await hass.async_block_till_done()

    writes = [
        request
        for request in session.requests
        if request["comhead"] in ("video switch", "preset save", "preset name")
    ]
    # Live routing is 1..8, the slot wants all-2: seven switches in (output 2
    # already matches), then the save and the rename, then seven switches back.
    assert writes[:7] == [
        {"comhead": "video switch", "source": [output, 2]}
        for output in (1, 3, 4, 5, 6, 7, 8)
    ]
    assert writes[7] == {"comhead": "preset save", "index": 1}
    assert writes[8] == {"comhead": "preset name", "index": 1, "name": "Desk PC"}
    assert writes[9:] == [
        {"comhead": "video switch", "source": [output, output]}
        for output in (1, 3, 4, 5, 6, 7, 8)
    ]

    assert get_state(hass, sensor(hass)).state == "off"


async def test_edid_drift_trips_and_restores(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A wiped EDID table is noticed by the poll and put back by restore."""
    inputs: dict[str, Any] = deepcopy(DEVICE_RESPONSES["get input status"])
    session = await setup_integration(
        make_session(overrides={"get input status": inputs})
    )

    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "backup_presets")},
            blocking=True,
        )
    assert get_state(hass, sensor(hass)).state == "off"

    # The wipe: every input falls back to the firmware's default profile.
    inputs["edid"][:] = [36] * 8
    await coordinator_of(hass).async_refresh()
    await hass.async_block_till_done()

    state = get_state(hass, sensor(hass))
    assert state.state == "on"
    assert state.attributes["mismatched_edid_inputs"] == list(range(1, 9))

    session.requests.clear()
    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "restore_presets")},
            blocking=True,
        )
    await hass.async_block_till_done()

    edid_writes = [r for r in session.requests if r["comhead"] == "set edid"]
    assert edid_writes == [
        {"comhead": "set edid", "edid": [source, 28]} for source in range(1, 7)
    ] + [
        {"comhead": "set edid", "edid": [7, 10]},
        {"comhead": "set edid", "edid": [8, 10]},
    ]
    assert get_state(hass, sensor(hass)).state == "off"


async def test_edid_change_through_ha_updates_the_backup(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_storage: dict[str, Any],
) -> None:
    """Picking an EDID in Home Assistant must not read as drift."""
    await setup_integration(make_session())

    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "backup_presets")},
            blocking=True,
        )

    target = entity_reg(hass).async_get_entity_id(
        "select", DOMAIN, f"{MAC}_input_1_edid"
    )
    assert target is not None
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: target, ATTR_OPTION: "1080P,2.0CH"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert stored_backup(hass, hass_storage)["input_edids"]["1"] == 1
    assert get_state(hass, sensor(hass)).state == "off"


async def test_recalling_a_preset_persists_it(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_storage: dict[str, Any],
) -> None:
    """The active preset is stored, not just held in memory.

    A reload while the matrix is unreachable leaves the entity's last state
    as "unavailable", which no name-matching restore can use.
    """
    await setup_integration(make_session())

    target = entity_reg(hass).async_get_entity_id("select", DOMAIN, f"{MAC}_preset")
    assert target is not None
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: target, ATTR_OPTION: "Console"},
        blocking=True,
    )

    assert stored_backup(hass, hass_storage)["active_preset"] == 3


async def test_a_stored_active_preset_survives_a_reload(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_storage: dict[str, Any],
) -> None:
    """After a reload the select reads the stored preset, not unknown."""
    await setup_integration(make_session())
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    target = entity_reg(hass).async_get_entity_id("select", DOMAIN, f"{MAC}_preset")
    assert target is not None
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: target, ATTR_OPTION: "Console"},
        blocking=True,
    )

    # The matrix is unreachable across the reload, so the entity's last
    # state is "unavailable" and only storage can carry the record.
    with patch(
        "custom_components.hdcvt_matrix.async_get_clientsession",
        return_value=make_session(),
    ):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert coordinator_of(hass).active_preset == 3
    assert get_state(hass, target).state == "Console"


async def test_active_preset_follows_the_live_routing(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Follow the device, not just our own recalls.

    A preset applied on the front panel shows up, and a route changed by
    hand clears the reading instead of leaving it stale.
    """
    session = await setup_integration(make_session())

    # Slot 1 holds the routing that is live, so backing up makes it match.
    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: [1, 2, 3, 4, 5, 6, 7, 8], 2: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "backup_presets")},
            blocking=True,
        )
    assert coordinator_of(hass).active_preset == 1

    # Someone recalls slot 2 on the front panel: the matrix reports the new
    # routing and nothing tells Home Assistant a preset was applied.
    session.set_routes(list(SLOT_ROUTES))
    await coordinator_of(hass).async_refresh()
    await hass.async_block_till_done()
    assert coordinator_of(hass).active_preset == 2

    # One output moved by hand: no preset is in effect any more.
    session.set_routes([3, *SLOT_ROUTES[1:]])
    await coordinator_of(hass).async_refresh()
    await hass.async_block_till_done()
    assert coordinator_of(hass).active_preset is None


async def test_a_failed_restore_is_reported(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Slots are read back afterwards, so a silent failure is not silent."""
    await setup_integration(make_session())

    with patch.object(
        MatrixTelnetClient,
        "async_command",
        new_callable=AsyncMock,
        side_effect=telnet_presets({1: SLOT_ROUTES}),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "backup_presets")},
            blocking=True,
        )

    # The device reports the slot as empty after the restore wrote it.
    with (
        patch.object(
            MatrixTelnetClient,
            "async_command",
            new_callable=AsyncMock,
            side_effect=telnet_presets({}),
        ),
        pytest.raises(HomeAssistantError, match="did not store preset 1"),
    ):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "restore_presets")},
            blocking=True,
        )


async def test_restore_without_backup_errors(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Nothing cached means nothing to restore, said out loud."""
    await setup_integration(make_session())

    with pytest.raises(HomeAssistantError, match="no preset backup"):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: button(hass, "restore_presets")},
            blocking=True,
        )


async def test_saving_through_ha_updates_the_backup(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_storage: dict[str, Any],
) -> None:
    """A save via Home Assistant snapshots the routes without telnet."""
    await setup_integration(make_session())

    target = entity_reg(hass).async_get_entity_id(
        "button", DOMAIN, f"{MAC}_save_preset_1"
    )
    assert target is not None
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: target}, blocking=True
    )

    data = stored_backup(hass, hass_storage)
    assert data["presets"]["1"] == {
        "name": "Desk PC",
        "routes": [1, 2, 3, 4, 5, 6, 7, 8],
    }
