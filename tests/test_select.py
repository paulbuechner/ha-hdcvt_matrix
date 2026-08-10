"""Tests for the HDCVT HDMI Matrix preset select."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

# Not in phcc's sparse __all__; see the note in conftest.
# noinspection PyProtectedMember
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.hdcvt_matrix.const import DOMAIN
from custom_components.hdcvt_matrix.registry import entity_reg

from .conftest import MAC, SetupIntegration, get_state, make_session


def entity_id(hass: HomeAssistant) -> str:
    """Resolve the select by unique id, rather than guessing its slug."""
    resolved = entity_reg(hass).async_get_entity_id("select", DOMAIN, f"{MAC}_preset")
    assert resolved is not None
    return resolved


def output_id(hass: HomeAssistant, output: int) -> str:
    """Resolve the select for a one-based output."""
    resolved = entity_reg(hass).async_get_entity_id(
        "select", DOMAIN, f"{MAC}_output_{output}"
    )
    assert resolved is not None
    return resolved


async def test_one_select_per_output(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """An 8x8 gets eight routing selects, sized from the device."""
    await setup_integration(make_session())

    for output in range(1, 9):
        assert hass.states.get(output_id(hass, output)) is not None
    assert (
        entity_reg(hass).async_get_entity_id("select", DOMAIN, f"{MAC}_output_9")
        is None
    )


async def test_output_reports_its_current_input(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Output 3 is fed by input 3 in the fixture, shown by input name."""
    await setup_integration(make_session())

    state = get_state(hass, output_id(hass, 3))
    assert state.state == "Input3"
    assert state.attributes["options"] == [f"Input{i}" for i in range(1, 9)]


async def test_routing_sends_output_then_input(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Selecting an input routes it to that output, one-based both ways."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: output_id(hass, 5), ATTR_OPTION: "Input2"},
        blocking=True,
    )

    switches = [r for r in session.requests if r["comhead"] == "video switch"]
    assert switches == [{"comhead": "video switch", "source": [5, 2]}]


async def test_routing_updates_state(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The select reflects the new input without waiting for the next poll."""
    await setup_integration(make_session())

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: output_id(hass, 5), ATTR_OPTION: "Input2"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert get_state(hass, output_id(hass, 5)).state == "Input2"


async def test_routing_rejects_an_unknown_input(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """An input the matrix does not have must not reach the device."""
    session = await setup_integration(make_session())

    target = output_id(hass, 1)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: target, ATTR_OPTION: "Nope"},
            blocking=True,
        )

    assert not [r for r in session.requests if r["comhead"] == "video switch"]


async def test_options_come_from_the_device(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Preset names on the matrix become the dropdown options."""
    await setup_integration(make_session())

    state = hass.states.get(entity_id(hass))
    assert state is not None
    assert state.attributes["options"] == [
        "Desk PC",
        "Laptop",
        "Console",
        "Preset4",
        "Preset5",
        "Preset6",
        "Preset7",
        "Preset8",
    ]


async def test_state_is_unknown_before_we_apply_one(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The firmware never reports an active preset, so we must not invent one."""
    await setup_integration(make_session())

    assert get_state(hass, entity_id(hass)).state == STATE_UNKNOWN


async def test_selecting_sends_the_one_based_index(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Picking the third option recalls preset 3."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id(hass), ATTR_OPTION: "Console"},
        blocking=True,
    )

    preset_calls = [r for r in session.requests if r["comhead"] == "preset set"]
    assert preset_calls == [{"comhead": "preset set", "index": 3}]


async def test_state_reflects_the_applied_preset(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Once we have applied one, the select reports it."""
    await setup_integration(make_session())

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id(hass), ATTR_OPTION: "Laptop"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert get_state(hass, entity_id(hass)).state == "Laptop"


async def test_unknown_option_is_rejected(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """An option the matrix does not have must not reach the device."""
    session = await setup_integration(make_session())

    target = entity_id(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: target, ATTR_OPTION: "Nope"},
            blocking=True,
        )

    assert not [r for r in session.requests if r["comhead"] == "preset set"]


async def test_device_refusal_surfaces(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A result:0 from the matrix becomes an error, not a silent success."""
    session = await setup_integration(
        make_session(overrides={"preset set": {"comhead": "preset set", "result": 0}})
    )

    target = entity_id(hass)

    with pytest.raises(HomeAssistantError, match="preset"):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: target, ATTR_OPTION: "Desk PC"},
            blocking=True,
        )

    assert get_state(hass, target).state == STATE_UNKNOWN
    assert session.requests[-1] == {"comhead": "preset set", "index": 1}


async def test_preset_recall_has_a_cooldown(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A second recall inside the settle window is refused, then allowed.

    The matrix takes 3-5 s to apply a preset; a recall fired into that
    window must not reach the device at all.
    """
    session = await setup_integration(make_session())

    async def recall(option: str) -> None:
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: entity_id(hass), ATTR_OPTION: option},
            blocking=True,
        )

    # Patching the module reference keeps the fake clock out of the event
    # loop's own time.monotonic calls.
    with patch("custom_components.hdcvt_matrix.coordinator.time") as mock_time:
        mock_time.monotonic.side_effect = [0.0, 2.0, 10.0]
        await recall("Desk PC")
        with pytest.raises(HomeAssistantError, match="still applying"):
            await recall("Laptop")
        await recall("Laptop")

    recalls = [r for r in session.requests if r["comhead"] == "preset set"]
    assert [r["index"] for r in recalls] == [1, 2]


def mode_id(hass: HomeAssistant, output: int, key: str) -> str:
    """Resolve a per-output mode select by unique id."""
    resolved = entity_reg(hass).async_get_entity_id(
        "select", DOMAIN, f"{MAC}_output_{output}_{key}"
    )
    assert resolved is not None
    return resolved


async def test_hdcp_maps_firmware_values_to_labels(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The fixture reports mode 3, which is Follow sink."""
    await setup_integration(make_session())

    state = get_state(hass, mode_id(hass, 1, "hdcp"))
    assert state.state == "follow_sink"
    assert state.attributes["options"] == [
        "hdcp_1_4",
        "hdcp_2_2",
        "follow_sink",
        "follow_source",
        "off",
    ]


async def test_hdcp_selection_sends_the_firmware_value(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Picking HDCP 2.2 sends value 2, not the option's list position."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: mode_id(hass, 6, "hdcp"), ATTR_OPTION: "hdcp_2_2"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "tx hdcp"]
    assert calls == [{"comhead": "tx hdcp", "hdcp": [6, 2]}]


async def test_scaler_offers_the_modes_the_web_ui_hides(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Modes 2 and 4 exist in the firmware even though the web UI hides them.

    Options map by firmware value, not list position: auto must still send 3.
    """
    session = await setup_integration(make_session())

    state = get_state(hass, mode_id(hass, 1, "scaler"))
    assert state.state == "bypass"
    assert state.attributes["options"] == [
        "bypass",
        "downscale_4k_to_1080p",
        "downscale_8k_4k_to_1080p",
        "auto",
        "audio_only",
    ]

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: mode_id(hass, 2, "scaler"), ATTR_OPTION: "auto"},
        blocking=True,
    )
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: mode_id(hass, 2, "scaler"), ATTR_OPTION: "audio_only"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set video scaler"]
    assert calls == [
        {"comhead": "set video scaler", "scaler": [2, 3]},
        {"comhead": "set video scaler", "scaler": [2, 4]},
    ]


async def test_unknown_firmware_mode_reads_as_none(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A value we have no label for must read unknown, not crash or guess."""
    await setup_integration(
        make_session(
            overrides={
                "get output status": {
                    "comhead": "get output status",
                    "power": 1,
                    "allconnect": [1] * 8,
                    "allhdcp": [99] * 9,
                    "allscaler": [0] * 9,
                    "allout": [1] * 9,
                    "allaudiomute": [1] * 9,
                }
            }
        )
    )

    assert get_state(hass, mode_id(hass, 1, "hdcp")).state == STATE_UNKNOWN


def edid_id(hass: HomeAssistant, source: int) -> str:
    """Resolve the EDID select for a one-based input."""
    resolved = entity_reg(hass).async_get_entity_id(
        "select", DOMAIN, f"{MAC}_input_{source}_edid"
    )
    assert resolved is not None
    return resolved


async def test_edid_decodes_the_firmware_id(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The fixture reports 28 on input 1 and 10 on input 7."""
    await setup_integration(make_session())

    assert get_state(hass, edid_id(hass, 1)).state == "4K120(444)_HDR,2.0CH"
    assert get_state(hass, edid_id(hass, 7)).state == "4K60(444),2.0CH"


async def test_edid_selection_sends_the_profile_id(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Picking a label sends its firmware id, one-based input first."""
    session = await setup_integration(make_session())

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: edid_id(hass, 2), ATTR_OPTION: "1080P,5.1CH"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set edid"]
    assert calls == [{"comhead": "set edid", "edid": [2, 2]}]


async def test_edid_offers_every_profile(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """All 47 firmware profiles, including the user and copy slots."""
    await setup_integration(make_session())

    options = get_state(hass, edid_id(hass, 1)).attributes["options"]
    assert len(options) == 47
    assert options[0] == "1080P,2.0CH"
    assert "User1_EDID" in options
    assert "COPY_FROM_OUTPUT_8" in options


def ext_audio_id(hass: HomeAssistant, output: int) -> str:
    """Resolve the de-embedded audio routing select for a one-based output."""
    resolved = entity_reg(hass).async_get_entity_id(
        "select", DOMAIN, f"{MAC}_ext_audio_{output}"
    )
    assert resolved is not None
    return resolved


async def test_audio_routing_is_unavailable_outside_matrix_mode(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """In the bind modes the matrix ignores audio routing, so do not offer it."""
    await setup_integration(make_session())  # fixture reports mode 0, bind to input

    assert get_state(hass, ext_audio_id(hass, 1)).state == STATE_UNAVAILABLE


async def test_audio_routing_works_in_matrix_mode(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Matrix mode is the one where the audio outputs route independently."""
    session = await setup_integration(
        make_session(
            overrides={
                "get ext-audio status": {
                    "comhead": "get ext-audio status",
                    "power": 1,
                    "mode": 2,
                    "allsource": [1, 2, 3, 4, 5, 6, 7, 8],
                    "allout": [0] * 8,
                    "alloutputname": [f"Output{i}" for i in range(1, 9)],
                    "index": 1,
                }
            }
        )
    )

    assert get_state(hass, ext_audio_id(hass, 2)).state == "Input2"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ext_audio_id(hass, 2), ATTR_OPTION: "Input5"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "ext-audio switch"]
    assert calls == [{"comhead": "ext-audio switch", "source": [2, 5]}]


async def test_audio_mode_selection(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The mode select drives how the audio outputs behave."""
    session = await setup_integration(make_session())

    target = entity_reg(hass).async_get_entity_id(
        "select", DOMAIN, f"{MAC}_ext_audio_mode"
    )
    assert target is not None
    assert get_state(hass, target).state == "bind_to_input"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: target, ATTR_OPTION: "audio_matrix"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set ext-audio mode"]
    assert calls == [{"comhead": "set ext-audio mode", "mode": 2}]


async def test_baud_rate_decodes_the_firmware_id(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Ids start at 1 here, so 6 is 115200 rather than an off-by-one."""
    session = await setup_integration(make_session())

    target = entity_reg(hass).async_get_entity_id("select", DOMAIN, f"{MAC}_baud_rate")
    assert target is not None
    assert get_state(hass, target).state == "115200"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: target, ATTR_OPTION: "9600"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set baudrate"]
    assert calls == [{"comhead": "set baudrate", "baudrate": 2}]


async def test_lcd_timeout_reads_the_mode_field(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """`mode` in get system status is the backlight timeout, not a matrix mode."""
    session = await setup_integration(make_session())

    target = entity_reg(hass).async_get_entity_id(
        "select", DOMAIN, f"{MAC}_lcd_on_time"
    )
    assert target is not None
    assert get_state(hass, target).state == "30_seconds"

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: target, ATTR_OPTION: "always_on"},
        blocking=True,
    )

    calls = [r for r in session.requests if r["comhead"] == "set lcd on time"]
    assert calls == [{"comhead": "set lcd on time", "lcd on time": 0}]


async def test_preset_survives_a_restart(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The firmware cannot report the active preset, so ours has to persist.

    It used to read unknown after every restart, reload and options change,
    since the only record of it lived in memory.
    """
    mock_restore_cache(hass, (State("select.hdp_mxc88a_preset", "Laptop"),))

    await setup_integration(make_session())

    assert get_state(hass, entity_id(hass)).state == "Laptop"


async def test_a_stale_restored_preset_is_ignored(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """A preset renamed on the device must not restore to a name it no longer has."""
    mock_restore_cache(hass, (State("select.hdp_mxc88a_preset", "Renamed Since"),))

    await setup_integration(make_session())

    assert get_state(hass, entity_id(hass)).state == STATE_UNKNOWN
