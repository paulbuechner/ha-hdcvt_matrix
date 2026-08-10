"""Fixtures for the HDCVT HDMI Matrix tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
import json
from types import TracebackType
from typing import Any
from unittest.mock import PropertyMock, patch

import aiohttp
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, State
import pytest

# phcc's __all__ lists two of its many public helpers, so PyCharm reads the
# rest as unexported. MockConfigEntry is its documented entry point.
# noinspection PyProtectedMember
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hdcvt_matrix.const import CONF_FEATURES, DOMAIN, FEATURES

pytest_plugins = "pytest_homeassistant_custom_component"

HOST = "192.168.10.60"
MAC = "6C:DF:FB:01:AB:CD"
UNIQUE_ID = "6c:df:fb:01:ab:cd"
HTTP_BAD_REQUEST = 400

# Signatures of the fixtures below, so tests taking them stay type-checked.
type SetupIntegration = Callable[..., Awaitable[FakeSession]]
type PatchClientSession = Callable[[FakeSession], AbstractContextManager[FakeSession]]

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
        "allscaler": [0] * 9,
        "allarc": [0] * 9,
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
    "get ext-audio status": {
        "comhead": "get ext-audio status",
        "power": 1,
        "mode": 0,
        "allsource": [1, 2, 3, 4, 5, 6, 7, 8],
        "allout": [0, 0, 0, 0, 0, 0, 0, 0],
        "allinputname": [f"Input{i}" for i in range(1, 9)],
        # Deliberately different from the video output names: the firmware
        # reports these separately, and reading the wrong list is an easy
        # mistake that identical fixtures would hide.
        "alloutputname": [f"Audio{i}" for i in range(1, 9)],
        "index": 1,
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
    "tx hdcp": {"comhead": "tx hdcp", "result": 1},
    "set video scaler": {"comhead": "set video scaler", "result": 1},
    "set panel lock": {"comhead": "set panel lock", "result": 1},
    "set beep": {"comhead": "set beep", "result": 1},
    "cec command": {"comhead": "cec command", "result": 1},
    "set arc": {"comhead": "set arc", "result": 1},
    "set edid": {"comhead": "set edid", "result": 1},
    "reboot": {"comhead": "reboot", "result": 1},
    "set baudrate": {"comhead": "set baudrate", "result": 1},
    "set lcd on time": {"comhead": "set lcd on time", "result": 1},
    "preset clear": {"comhead": "preset clear", "result": 1},
    "preset name": {"comhead": "preset name", "result": 1},
    "set input name": {"comhead": "set input name", "result": 1},
    "set output name": {"comhead": "set output name", "result": 1},
    "ext-audio switch": {"comhead": "ext-audio switch", "result": 1},
    "set ext-audio out": {"comhead": "set ext-audio out", "result": 1},
    "set ext-audio mode": {"comhead": "set ext-audio mode", "result": 1},
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

    def __init__(
        self,
        handler: Callable[[dict[str, Any]], FakeResponse],
        state: dict[str, Any] | None = None,
    ) -> None:
        """Store the handler and start a call log."""
        self._handler = handler
        self._state = state if state is not None else {}
        self.requests: list[dict[str, Any]] = []

    def set_routes(self, routes: list[int]) -> None:
        """Reroute the fake device behind Home Assistant's back.

        What the front panel, the IR remote and the web UI all do: the next
        poll reports new routing with nothing having been asked of us.
        """
        aggregate = self._state.get("allsource", [])[len(routes) :]
        self._state["allsource"] = [*routes, *aggregate]

    def post(self, url: str, *, json: Any, timeout: Any = None) -> FakeResponse:
        """Record the request and hand back the canned response."""
        self.requests.append(json)
        return self._handler(json)


def _fixture_list(responses: dict[str, Any], comhead: str, key: str) -> list[Any]:
    """Return a mutable list field from one of the canned replies."""
    body = responses.get(comhead)
    value = body.get(key) if isinstance(body, dict) else None
    return value if isinstance(value, list) else []


def _apply_stateful_write(
    state: dict[str, Any], responses: dict[str, Any], payload: dict[str, Any]
) -> bool:
    """Model a write on the fake device; True when the command is one of ours."""
    comhead = payload["comhead"]
    if comhead == "set poweronoff":
        state["power"] = int(payload["power"])
    elif comhead == "video switch":
        output, source = payload["source"]
        if 1 <= output <= len(state["allsource"]):
            state["allsource"][output - 1] = source
    elif comhead == "preset name":
        names = _fixture_list(responses, "get video status", "allname")
        if 1 <= payload["index"] <= len(names):
            names[payload["index"] - 1] = payload["name"]
    elif comhead == "set edid":
        source, profile = payload["edid"]
        edids = _fixture_list(responses, "get input status", "edid")
        if 1 <= source <= len(edids):
            edids[source - 1] = profile
    else:
        return False
    return True


def make_session(
    *,
    login_ok: bool = True,
    overrides: dict[str, Any] | None = None,
    exc: Exception | None = None,
) -> FakeSession:
    """Build a session that answers like a real matrix.

    Power, routing, preset names and EDIDs are modelled statefully: ``set
    poweronoff``, ``video switch``, ``preset name`` and ``set edid`` update
    them, and every later reply reports the new value, the way the real
    device behaves once it has settled. Override a command explicitly to
    simulate a refusal instead. The defaults are deep-copied so that
    statefulness cannot leak between tests; an override stays the caller's
    object, so a test can mutate it to simulate on-device changes.
    """
    overrides = overrides or {}
    responses = {**deepcopy(DEVICE_RESPONSES), **overrides}
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
        for comhead in ("set poweronoff", "video switch", "preset name", "set edid")
        if comhead not in overrides
    }

    def handler(payload: dict[str, Any]) -> FakeResponse:
        if exc is not None:
            raise exc
        comhead = payload["comhead"]

        if comhead in stateful and _apply_stateful_write(state, responses, payload):
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

    return FakeSession(handler, state)


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


@pytest.fixture(autouse=True)
def auto_enable_all_entities() -> Iterator[None]:
    """Register even the opt-in entities, so tests can exercise them.

    Most entities ship disabled so a fresh install does not add ~90 of them.
    Which ones ship enabled is pinned separately in test_defaults.py.
    """
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def patch_clientsession() -> PatchClientSession:
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

    async def _setup(
        session: FakeSession, features: list[str] | None = None
    ) -> FakeSession:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=UNIQUE_ID,
            title="HDP-MXC88A",
            data={CONF_HOST: HOST},
            # Most tests exercise the optional entities, so switch every
            # feature on by default. Pass features=[] for the untouched
            # install, or a subset to check one group in isolation.
            options={CONF_FEATURES: list(FEATURES) if features is None else features},
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
