"""Fixtures for the HDCVT HDMI Matrix tests."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hdcvt_matrix.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

HOST = "192.168.10.60"
MAC = "6C:DF:FB:01:AB:CD"
UNIQUE_ID = "6c:df:fb:01:ab:cd"
HTTP_BAD_REQUEST = 400

# Signatures of the fixtures below, so tests taking them stay type-checked.
type SetupIntegration = Callable[[FakeSession], Awaitable[FakeSession]]
type PatchClientsession = Callable[[FakeSession], AbstractContextManager[FakeSession]]

# Captured verbatim from an HDP-MXC88A on firmware V1.00.16 / web V2.00.21.
# Note the 9-element arrays on an 8x8: the last entry is the "all ports"
# aggregate the web UI uses, not a real port.
DEVICE_RESPONSES: dict[str, dict[str, Any]] = {
    "get status": {
        "comhead": "get status",
        "power": 1,
        "version": "V1.00.16",
        "hostname": "IP-module-ABCD",
        "ipaddress": "192.168.10.60",
        "subnet": "255.255.255.0",
        "gateway": "192.168.10.1",
        "macaddress": "6C:DF:FB:01:AB:CD",
        "model": "HDP-MXC88A",
        "webversion": "V2.00.21",
    },
    "get video status": {
        "comhead": "get video status",
        "power": 1,
        "allsource": [1, 2, 3, 4, 5, 6, 7, 8, 0],
        "allinputname": [f"Input{i}" for i in range(1, 9)],
        "alloutputname": [f"Output{i}" for i in range(1, 9)],
        # Presets 1-3 stand in for user-renamed scenes, 4-8 for stock names.
        "allname": [
            "Desk PC",
            "Laptop",
            "Console",
            *[f"Preset{i}" for i in range(4, 9)],
        ],
    },
    "get output status": {
        "comhead": "get output status",
        "power": 1,
        "allconnect": [1, 1, 1, 0, 0, 0, 0, 0],
        "name": [f"Output{i}" for i in range(1, 9)],
        "allhdcp": [3] * 9,
        "allout": [1] * 9,
        "allaudiomute": [1] * 9,
    },
    "get input status": {
        "comhead": "get input status",
        "power": 1,
        "edid": [28, 28, 28, 28, 28, 28, 10, 10],
        "inactive": [1, 1, 1, 0, 0, 0, 0, 0],
        "inname": [f"Input{i}" for i in range(1, 9)],
    },
    "get system status": {
        "comhead": "get system status",
        "power": 1,
        "baudrate": 6,
        "beep": 0,
        "lock": 0,
        "mode": 3,
    },
    "get network": {
        "comhead": "get network",
        "power": 1,
        "dhcp": 1,
        "ipaddress": "192.168.10.60",
        "subnet": "255.255.255.0",
        "gateway": "192.168.10.1",
        "telnetport": 23,
        "tcpport": 8000,
        "macaddress": "6C:DF:FB:01:AB:CD",
        "hostname": "IP-module-ABCD",
        "model": "HDP-MXC88A",
    },
    "video switch": {"comhead": "video switch", "result": 1},
    "set poweronoff": {"comhead": "set poweronoff", "result": 1},
    "preset set": {"comhead": "preset set", "result": 1},
    "preset save": {"comhead": "preset save", "result": 1},
    "tx stream": {"comhead": "tx stream", "result": 1},
    "set output audio mute": {"comhead": "set output audio mute", "result": 1},
}


class FakeResponse:
    """Minimal stand-in for an aiohttp response used as an async context manager."""

    def __init__(self, body: str, status: int = 200) -> None:
        """Store the canned body."""
        self._body = body
        self.status = status

    def raise_for_status(self) -> None:
        """Mimic aiohttp's status check.

        Raises the base ClientError rather than ClientResponseError, which
        needs a real RequestInfo we have nothing sensible to put in. The client
        catches ClientError, so this exercises the same path.
        """
        if self.status >= HTTP_BAD_REQUEST:
            raise aiohttp.ClientError(f"HTTP {self.status}")

    async def text(self) -> str:
        """Return the canned body."""
        return self._body

    async def __aenter__(self) -> FakeResponse:
        """Enter the context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the context manager."""


class FakeSession:
    """Session stand-in dispatching on the request body's ``comhead``."""

    def __init__(self, handler: Callable[[dict[str, Any]], FakeResponse]) -> None:
        """Store the handler and start a call log."""
        self._handler = handler
        self.requests: list[dict[str, Any]] = []

    def post(self, url: str, *, json: Any, timeout: Any = None) -> FakeResponse:
        """Record the request and hand back the canned response."""
        self.requests.append(json)
        return self._handler(json)


def make_session(
    *,
    login_ok: bool = True,
    overrides: dict[str, Any] | None = None,
    exc: Exception | None = None,
) -> FakeSession:
    """Build a session that answers like a real matrix.

    Power and routing are modelled statefully: ``set poweronoff`` and
    ``video switch`` update them, and every later reply reports the new value,
    the way the real device behaves once it has settled. Override a command
    explicitly to simulate a refusal instead.
    """
    overrides = overrides or {}
    responses = {**DEVICE_RESPONSES, **overrides}
    responses.setdefault("login", {"comhead": "login", "result": 1 if login_ok else 0})

    video = responses.get("get video status")
    video = video if isinstance(video, dict) else {}
    state: dict[str, Any] = {
        "power": int(video.get("power", 1)),
        # Keeps the trailing "all ports" aggregate, like the firmware does.
        "allsource": list(video.get("allsource", [])),
    }
    stateful = {
        comhead
        for comhead in ("set poweronoff", "video switch")
        if comhead not in overrides
    }

    def handler(payload: dict[str, Any]) -> FakeResponse:
        if exc is not None:
            raise exc
        comhead = payload["comhead"]

        if comhead == "set poweronoff" and comhead in stateful:
            state["power"] = int(payload["power"])
            return FakeResponse(json.dumps({"comhead": comhead, "result": 1}))

        if comhead == "video switch" and comhead in stateful:
            output, source = payload["source"]
            if 1 <= output <= len(state["allsource"]):
                state["allsource"][output - 1] = source
            return FakeResponse(json.dumps({"comhead": comhead, "result": 1}))

        if comhead not in responses:
            # The firmware answers unknown commands with plain text.
            return FakeResponse(f"not wait comhead [{comhead}]")

        body = responses[comhead]
        if isinstance(body, str):
            return FakeResponse(body)
        if "allsource" in body and state["allsource"]:
            body = {**body, "allsource": list(state["allsource"])}
        if "power" in body:
            body = {**body, "power": state["power"]}
        return FakeResponse(json.dumps(body))

    return FakeSession(handler)


def get_state(hass: HomeAssistant, entity_id: str) -> State:
    """Return an entity's state, failing loudly if the entity does not exist.

    `hass.states.get` is Optional, and chaining off it means a missing entity
    surfaces as an AttributeError rather than a useful message.
    """
    state = hass.states.get(entity_id)
    assert state is not None, f"no state for {entity_id}"
    return state


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make the custom integration loadable in every test."""
    return


@pytest.fixture
def patch_clientsession() -> PatchClientsession:
    """Patch the client session in both the flow and the entry setup.

    A finished flow creates an entry that Home Assistant then sets up, so
    patching only the flow would let that setup reach a real socket.
    """

    @contextmanager
    def _patch(session: FakeSession) -> Iterator[FakeSession]:
        with (
            patch(
                "custom_components.hdcvt_matrix.config_flow.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.hdcvt_matrix.async_get_clientsession",
                return_value=session,
            ),
        ):
            yield session

    return _patch


@pytest.fixture
def setup_integration(hass: HomeAssistant) -> SetupIntegration:
    """Set the integration up against a fake session, and hand that session back."""

    async def _setup(session: FakeSession) -> FakeSession:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=UNIQUE_ID,
            title="HDP-MXC88A",
            data={CONF_HOST: HOST},
        )
        entry.add_to_hass(hass)
        # Patch only for setup; the client keeps the session it was handed, so
        # later calls still land on the fake.
        with patch(
            "custom_components.hdcvt_matrix.async_get_clientsession",
            return_value=session,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        return session

    return _setup
