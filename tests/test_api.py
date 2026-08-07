"""Tests for the HDCVT matrix HTTP client."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from custom_components.hdcvt_matrix.api import (
    READ_ATTEMPTS,
    HdcvtMatrixClient,
    MatrixAuthError,
    MatrixConnectionError,
    MatrixResponseError,
)

from .conftest import FakeResponse, make_session

HOST = "192.168.10.60"


async def test_get_info_parses_identity() -> None:
    """Model, MAC and firmware come back from ``get status``."""
    client = HdcvtMatrixClient(HOST, make_session())

    info = await client.async_get_info()

    assert info.model == "HDP-MXC88A"
    assert info.mac_address == "6C:DF:FB:01:AB:CD"
    assert info.firmware == "V1.00.16"
    assert info.hostname == "IP-module-ABCD"


async def test_get_state_trims_trailing_aggregate() -> None:
    """The 9th array entry is the web UI's bulk value, not a 9th port."""
    client = HdcvtMatrixClient(HOST, make_session())

    state = await client.async_get_state()

    assert state.output_count == 8
    assert state.input_count == 8
    assert state.routes == [1, 2, 3, 4, 5, 6, 7, 8]
    assert state.preset_names[0] == "Desk PC"


async def test_polling_reads_only_what_entities_consume() -> None:
    """The CGI backend is single threaded, so a poll must not fan out.

    Four commands, each backing real entities: routing, the output switches
    and modes, the input signal sensors, and the front panel switches.
    Anything else belongs in the diagnostics snapshot.
    """
    session = make_session()
    client = HdcvtMatrixClient(HOST, session)

    await client.async_get_state()

    assert session.requests == [
        {"comhead": "get video status"},
        {"comhead": "get output status"},
        {"comhead": "get input status"},
        {"comhead": "get system status"},
    ]


async def test_raw_snapshot_reads_everything() -> None:
    """Diagnostics pays for the full picture, off the polling path."""
    session = make_session()
    client = HdcvtMatrixClient(HOST, session)

    snapshot = await client.async_get_raw_snapshot()

    assert set(snapshot) == {
        "get status",
        "get video status",
        "get output status",
        "get input status",
        "get system status",
        "get network",
    }
    assert snapshot["get status"]["model"] == "HDP-MXC88A"


async def test_raw_snapshot_survives_a_failing_command() -> None:
    """One unsupported command must not sink the whole diagnostics download."""
    client = HdcvtMatrixClient(
        HOST, make_session(overrides={"get system status": "not wait comhead"})
    )

    snapshot = await client.async_get_raw_snapshot()

    assert "error" in snapshot["get system status"]
    assert snapshot["get video status"]["comhead"] == "get video status"


async def test_login_accepted() -> None:
    """A ``result: 1`` login is accepted silently."""
    session = make_session(login_ok=True)
    client = HdcvtMatrixClient(HOST, session, username="admin", password="pw")

    await client.async_login()

    assert session.requests[0] == {
        "comhead": "login",
        "user": "admin",
        "password": "pw",
    }


async def test_login_rejected() -> None:
    """A ``result: 0`` login raises."""
    client = HdcvtMatrixClient(
        HOST, make_session(login_ok=False), username="admin", password="wrong"
    )

    with pytest.raises(MatrixAuthError):
        await client.async_login()


async def test_login_skipped_without_username() -> None:
    """No credentials means no login round trip, since reads are unauthenticated."""
    session = make_session()
    client = HdcvtMatrixClient(HOST, session)

    await client.async_login()

    assert session.requests == []


async def test_non_json_reply_raises() -> None:
    """Unknown commands answer in plain text and must not crash the parser."""
    client = HdcvtMatrixClient(
        HOST, make_session(overrides={"get status": "not wait comhead [get status]"})
    )

    with pytest.raises(MatrixResponseError):
        await client.async_get_info()


async def test_connection_error_wrapped() -> None:
    """Aiohttp failures surface as MatrixConnectionError."""
    client = HdcvtMatrixClient(HOST, make_session(exc=aiohttp.ClientError("boom")))

    with pytest.raises(MatrixConnectionError):
        await client.async_get_info()


async def test_missing_mac_rejected() -> None:
    """A reply without a MAC is not a matrix we can identify."""
    client = HdcvtMatrixClient(
        HOST,
        make_session(overrides={"get status": {"comhead": "get status", "power": 1}}),
    )

    with pytest.raises(MatrixResponseError):
        await client.async_get_info()


async def test_set_route_sends_output_then_input() -> None:
    """``source`` is [output, input], both one-based."""
    session = make_session()
    client = HdcvtMatrixClient(HOST, session)

    await client.async_set_route(output=3, source=7)

    assert session.requests[-1] == {
        "comhead": "video switch",
        "source": [3, 7],
    }


async def test_set_power() -> None:
    """Power maps to an int flag."""
    session = make_session()
    client = HdcvtMatrixClient(HOST, session)

    await client.async_set_power(on=True)

    assert session.requests[-1] == {"comhead": "set poweronoff", "power": 1}


async def test_a_busy_matrix_does_not_fail_the_poll() -> None:
    """A heavy command leaves the CGI answering empty for a moment.

    Without a retry that stumble fails the whole update and every entity goes
    unavailable until the next cycle, which is what a preset recall used to do.
    """
    session = make_session()
    real = session._handler
    calls = {"n": 0}

    def flaky(payload: dict[str, Any]) -> FakeResponse:
        calls["n"] += 1
        if payload["comhead"] == "get video status" and calls["n"] == 1:
            return FakeResponse("")  # busy: empty body, not an error
        return real(payload)

    session._handler = flaky

    state = await HdcvtMatrixClient(HOST, session).async_get_state()

    assert state.output_count == 8
    reads = [r for r in session.requests if r["comhead"] == "get video status"]
    assert len(reads) == 2, "should have retried the busy read exactly once"


async def test_reads_give_up_eventually() -> None:
    """Retrying is bounded; a genuinely dead matrix still surfaces."""
    session = make_session(overrides={"get video status": ""})
    client = HdcvtMatrixClient(HOST, session)

    with pytest.raises(MatrixResponseError):
        await client.async_get_state()

    reads = [r for r in session.requests if r["comhead"] == "get video status"]
    assert len(reads) == READ_ATTEMPTS


async def test_writes_are_never_retried() -> None:
    """Writes are not idempotent, so a failure must not be repeated."""
    session = make_session(overrides={"video switch": ""})
    client = HdcvtMatrixClient(HOST, session)

    with pytest.raises(MatrixResponseError):
        await client.async_set_route(output=1, source=2)

    writes = [r for r in session.requests if r["comhead"] == "video switch"]
    assert len(writes) == 1
