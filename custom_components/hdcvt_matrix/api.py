"""Async client for HDCVT web-controlled HDMI matrices.

The firmware exposes a single JSON-RPC-ish endpoint at ``/cgi-bin/instr``. Every
request is a POST whose body carries a ``comhead`` naming the command; responses
echo the ``comhead`` back alongside the payload.

Two firmware quirks drive the design here:

* Unknown commands are answered with **plain text** (``not wait comhead [...]``)
  rather than JSON, so replies are parsed defensively.
* The API is **sessionless**. ``login`` validates credentials and returns
  ``result: 1``/``result: 0``, but it hands out no token and every other command
  answers unauthenticated. Credentials are therefore verified explicitly at
  setup rather than relied upon to gate reads.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Final, Protocol

import aiohttp

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT

_LOGGER = logging.getLogger(__name__)

CGI_INSTR: Final = "/cgi-bin/instr"

# The protocol names its command field this; every payload carries one.
KEY_COMHEAD: Final = "comhead"

# Reads are retried while the matrix is busy after a heavy command. Writes are
# not: they are not idempotent.
READ_ATTEMPTS: Final = 3
READ_RETRY_DELAY: Final = 0.4

CMD_LOGIN: Final = "login"
CMD_GET_STATUS: Final = "get status"
CMD_GET_VIDEO_STATUS: Final = "get video status"
CMD_GET_OUTPUT_STATUS: Final = "get output status"
CMD_GET_INPUT_STATUS: Final = "get input status"
CMD_GET_SYSTEM_STATUS: Final = "get system status"
CMD_GET_NETWORK: Final = "get network"
CMD_VIDEO_SWITCH: Final = "video switch"
CMD_SET_POWER: Final = "set poweronoff"
CMD_PRESET_SET: Final = "preset set"
CMD_PRESET_SAVE: Final = "preset save"
CMD_TX_STREAM: Final = "tx stream"
CMD_SET_AUDIO_MUTE: Final = "set output audio mute"
CMD_TX_HDCP: Final = "tx hdcp"
# The web UI's own command map says "video scaler", but the firmware rejects
# that and only answers to "set video scaler". Verified against the device.
CMD_SET_SCALER: Final = "set video scaler"
CMD_SET_PANEL_LOCK: Final = "set panel lock"
CMD_SET_BEEP: Final = "set beep"
CMD_CEC_COMMAND: Final = "cec command"
CMD_SET_ARC: Final = "set arc"
CMD_SET_EDID: Final = "set edid"

# CEC targets. "port" is a mask over all ports, not a port number, and it is
# passed per command: it does not disturb the selection stored by
# "set cec index".
CEC_OBJECT_INPUT: Final = 0
CEC_OBJECT_OUTPUT: Final = 1

# Output CEC command ids. Inputs use a *different* numbering for the same
# actions (1 = on, 2 = off), so do not reuse these for CEC_OBJECT_INPUT.
CEC_OUTPUT_POWER_ON: Final = 0
CEC_OUTPUT_POWER_OFF: Final = 1

# Firmware value -> option key. Labels live in the translation files.
HDCP_MODES: Final[dict[int, str]] = {
    1: "hdcp_1_4",
    2: "hdcp_2_2",
    3: "follow_sink",
    4: "follow_source",
    5: "off",
}
# EDID profiles the firmware accepts, lifted from the web UI. Ids 37-39 are
# the user-uploaded slots and 40+ copy the EDID from an output.
EDID_PROFILES: Final[dict[int, str]] = {
    1: "1080P,2.0CH",
    2: "1080P,5.1CH",
    3: "1080P,7.1CH",
    4: "4K30,2.0CH",
    5: "4K30,5.1CH",
    6: "4K30,7.1CH",
    7: "4K60(420),2.0CH",
    8: "4K60(420),5.1CH",
    9: "4K60(420),7.1CH",
    10: "4K60(444),2.0CH",
    11: "4K60(444),5.1CH",
    12: "4K60(444),7.1CH",
    13: "1080P_HDR,2.0CH",
    14: "1080P_HDR,5.1CH",
    15: "1080P_HDR,7.1CH",
    16: "4K30_HDR,2.0CH",
    17: "4K30_HDR,5.1CH",
    18: "4K30_HDR,7.1CH",
    19: "4K60(420)_HDR,2.0CH",
    20: "4K60(420)_HDR,5.1CH",
    21: "4K60(420)_HDR,7.1CH",
    22: "4K60(444)_HDR,2.0CH",
    23: "4K60(444)_HDR,5.1CH",
    24: "4K60(444)_HDR,7.1CH",
    25: "4K120(420)_HDR,2.0CH",
    26: "4K120(420)_HDR,5.1CH",
    27: "4K120(420)_HDR,7.1CH",
    28: "4K120(444)_HDR,2.0CH",
    29: "4K120(444)_HDR,5.1CH",
    30: "4K120(444)_HDR,7.1CH",
    31: "FRL10G_8K_HDR,2.0CH",
    32: "FRL10G_8K_HDR,5.1CH",
    33: "FRL10G_8K_HDR,7.1CH",
    34: "FRL12G_8K_HDR,2.0CH",
    35: "FRL12G_8K_HDR,5.1CH",
    36: "FRL12G_8K_HDR,7.1CH",
    37: "User1_EDID",
    38: "User2_EDID",
    39: "User3_EDID",
    40: "COPY_FROM_OUTPUT_1",
    41: "COPY_FROM_OUTPUT_2",
    42: "COPY_FROM_OUTPUT_3",
    43: "COPY_FROM_OUTPUT_4",
    44: "COPY_FROM_OUTPUT_5",
    45: "COPY_FROM_OUTPUT_6",
    46: "COPY_FROM_OUTPUT_7",
    47: "COPY_FROM_OUTPUT_8",
}

# Note the gap: the firmware has no scaler mode 2.
SCALER_MODES: Final[dict[int, str]] = {
    0: "bypass",
    1: "downscale_4k_to_1080p",
    3: "auto",
}


class _ResponseLike(Protocol):
    """The part of an HTTP response this client touches."""

    def raise_for_status(self) -> None:
        """Raise if the reply carried an error status."""

    async def text(self) -> str:
        """Return the body as text."""


class _ResponseContext(Protocol):
    """An async context manager yielding a response."""

    async def __aenter__(self) -> _ResponseLike:
        """Enter the context."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the context."""


class MatrixSession(Protocol):
    """The slice of ``aiohttp.ClientSession`` this client depends on.

    Narrower than the real thing on purpose. It documents the exact surface
    used, and lets a test supply a fake that genuinely satisfies the contract
    rather than being cast into place.
    """

    def post(
        self, url: str, *, json: Any, timeout: aiohttp.ClientTimeout
    ) -> _ResponseContext:
        """POST a JSON body and return the response context."""


class MatrixError(Exception):
    """Base error for all matrix client failures."""


class MatrixConnectionError(MatrixError):
    """The matrix could not be reached."""


class MatrixResponseError(MatrixError):
    """The matrix replied with something we cannot parse or did not expect."""


class MatrixAuthError(MatrixError):
    """The matrix rejected the supplied credentials."""


@dataclass(frozen=True, slots=True)
class MatrixInfo:
    """Identity of the matrix, read once during setup."""

    model: str
    hostname: str
    mac_address: str
    firmware: str


@dataclass(slots=True)
class MatrixState:
    """Mutable state of the matrix, refreshed on every poll."""

    power: bool
    # Index is the zero-based output, value is the one-based input feeding it.
    routes: list[int] = field(default_factory=list)
    input_names: list[str] = field(default_factory=list)
    output_names: list[str] = field(default_factory=list)
    preset_names: list[str] = field(default_factory=list)
    # A source is detected on this input / a sink is detected on this output.
    input_active: list[bool] = field(default_factory=list)
    output_connected: list[bool] = field(default_factory=list)
    # Output stream enabled, and output audio muted.
    output_enabled: list[bool] = field(default_factory=list)
    audio_muted: list[bool] = field(default_factory=list)
    # Raw per-output mode values; see HDCP_MODES and SCALER_MODES.
    hdcp_modes: list[int] = field(default_factory=list)
    scaler_modes: list[int] = field(default_factory=list)
    # ARC on the output, and the EDID profile id on each input.
    arc_enabled: list[bool] = field(default_factory=list)
    input_edids: list[int] = field(default_factory=list)
    # Front panel state.
    panel_locked: bool = False
    beep_enabled: bool = False

    @property
    def input_count(self) -> int:
        """Number of physical inputs."""
        return len(self.input_names)

    @property
    def output_count(self) -> int:
        """Number of physical outputs."""
        return len(self.output_names)


class HdcvtMatrixClient:
    """Talk to a single HDCVT matrix over HTTP."""

    def __init__(
        self,
        host: str,
        session: MatrixSession,
        *,
        username: str | None = None,
        password: str | None = None,
        port: int = DEFAULT_PORT,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise the client."""
        self._host = host
        self._session = session
        self._username = username
        self._password = password
        self._port = port
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        # The CGI backend is single threaded; serialise so a burst of commands
        # cannot make it drop replies.
        self._lock = asyncio.Lock()

    @property
    def host(self) -> str:
        """Host the client is bound to."""
        return self._host

    async def _async_read(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a read command, retrying while the matrix is busy.

        Heavy operations — recalling a preset, changing power, sending CEC —
        leave the single-threaded CGI unresponsive for a moment, and it answers
        with an empty body rather than an error. Without a retry that one
        stumble fails the whole poll and every entity goes unavailable until
        the next cycle. Reads are idempotent, so retrying is safe.
        """
        for attempt in range(READ_ATTEMPTS):
            try:
                return await self._async_command(payload)
            except (MatrixConnectionError, MatrixResponseError):
                if attempt == READ_ATTEMPTS - 1:
                    raise
                _LOGGER.debug(
                    "%s busy on %r, retrying", self._host, payload[KEY_COMHEAD]
                )
                await asyncio.sleep(READ_RETRY_DELAY * (attempt + 1))
        raise AssertionError  # unreachable, but mypy cannot see that

    async def _async_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one command and return the decoded reply."""
        # The firmware serves plain HTTP only; it has no TLS listener at all.
        url = f"http://{self._host}:{self._port}{CGI_INSTR}"  # NOSONAR
        async with self._lock:
            try:
                async with self._session.post(
                    url, json=payload, timeout=self._timeout
                ) as response:
                    response.raise_for_status()
                    # The firmware mislabels its content type, so decode by hand.
                    body = await response.text()
            except TimeoutError as err:
                raise MatrixConnectionError(
                    f"Timed out talking to {self._host}"
                ) from err
            except aiohttp.ClientError as err:
                raise MatrixConnectionError(
                    f"Cannot reach {self._host}: {err}"
                ) from err

        try:
            data = json.loads(body)
        except ValueError as err:
            raise MatrixResponseError(
                f"{self._host} returned a non-JSON reply to "
                f"{payload[KEY_COMHEAD]!r}: {body[:120]!r}"
            ) from err

        if not isinstance(data, dict):
            raise MatrixResponseError(
                f"{self._host} returned {type(data).__name__}, expected an object"
            )
        return data

    async def async_login(self) -> None:
        """Verify the configured credentials.

        No-op when no username is configured, since the API answers reads
        without authentication anyway.
        """
        if not self._username:
            return

        data = await self._async_command(
            {
                KEY_COMHEAD: CMD_LOGIN,
                "user": self._username,
                "password": self._password or "",
            }
        )
        if data.get("result") != 1:
            raise MatrixAuthError(
                f"{self._host} rejected the credentials for {self._username!r}"
            )
        _LOGGER.debug("Credentials accepted by %s", self._host)

    async def async_get_info(self) -> MatrixInfo:
        """Read the immutable identity of the matrix."""
        data = await self._async_read({KEY_COMHEAD: CMD_GET_STATUS})
        mac = str(data.get("macaddress") or "").strip()
        if not mac:
            raise MatrixResponseError(
                f"{self._host} reported no MAC address; not an HDCVT matrix?"
            )
        return MatrixInfo(
            model=str(data.get("model") or "HDMI Matrix"),
            hostname=str(data.get("hostname") or self._host),
            mac_address=mac.upper(),
            firmware=str(data.get("version") or ""),
        )

    async def async_get_state(self) -> MatrixState:
        """Read the routing and port state.

        Three requests, and no more: the CGI backend is single threaded and
        this runs on every poll, so it reads only what entities consume. The
        port-detection and output commands are here because the binary sensors
        and output switches need them, not speculatively. Anything else stays
        in async_get_raw_snapshot, off the polling path.
        """
        video = await self._async_read({KEY_COMHEAD: CMD_GET_VIDEO_STATUS})

        power = bool(video.get("power", 1))
        input_names = _str_list(video.get("allinputname"))
        output_names = _str_list(video.get("alloutputname"))
        if not input_names or not output_names:
            if power:
                raise MatrixResponseError(
                    f"{self._host} reported no port names; cannot size the matrix"
                )
            # In standby the IP module stays reachable but the matrix itself may
            # report nothing useful. Surface that as "off" rather than failing
            # the update, so the power control stays available to switch it back
            # on.
            return MatrixState(power=False)

        outputs = await self._async_read({KEY_COMHEAD: CMD_GET_OUTPUT_STATUS})
        inputs = await self._async_read({KEY_COMHEAD: CMD_GET_INPUT_STATUS})
        system = await self._async_read({KEY_COMHEAD: CMD_GET_SYSTEM_STATUS})

        # Array-valued fields carry one trailing "all ports" aggregate that the
        # web UI uses for its bulk controls. Trim it off using the port names,
        # which are the only arrays sized to the real port count.
        outs = len(output_names)
        ins = len(input_names)

        return MatrixState(
            power=power,
            routes=_int_list(video.get("allsource"))[:outs],
            input_names=input_names,
            output_names=output_names,
            preset_names=_str_list(video.get("allname")),
            input_active=_bool_list(inputs.get("inactive"), ins),
            output_connected=_bool_list(outputs.get("allconnect"), outs),
            output_enabled=_bool_list(outputs.get("allout"), outs),
            audio_muted=_bool_list(outputs.get("allaudiomute"), outs),
            hdcp_modes=_int_list(outputs.get("allhdcp"))[:outs],
            arc_enabled=_bool_list(outputs.get("allarc"), outs),
            input_edids=_int_list(inputs.get("edid"))[:ins],
            scaler_modes=_int_list(outputs.get("allscaler"))[:outs],
            panel_locked=bool(system.get("lock", 0)),
            beep_enabled=bool(system.get("beep", 0)),
        )

    async def async_get_raw_snapshot(self) -> dict[str, Any]:
        """Read every status command verbatim, for diagnostics.

        Off the polling path on purpose: this is several requests and only runs
        when someone downloads diagnostics.
        """
        snapshot: dict[str, Any] = {}
        for comhead in (
            CMD_GET_STATUS,
            CMD_GET_VIDEO_STATUS,
            CMD_GET_OUTPUT_STATUS,
            CMD_GET_INPUT_STATUS,
            CMD_GET_SYSTEM_STATUS,
            CMD_GET_NETWORK,
        ):
            try:
                snapshot[comhead] = await self._async_command({KEY_COMHEAD: comhead})
            except MatrixError as err:
                snapshot[comhead] = {"error": str(err)}
        return snapshot

    async def async_set_route(self, output: int, source: int) -> None:
        """Route one-based ``source`` to one-based ``output``."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_VIDEO_SWITCH, "source": [output, source]}
        )
        _raise_for_result(data, f"routing input {source} to output {output}")

    async def async_set_power(self, *, on: bool) -> None:
        """Switch the matrix on or into standby."""
        data = await self._async_command({KEY_COMHEAD: CMD_SET_POWER, "power": int(on)})
        _raise_for_result(data, "setting power")

    async def async_apply_preset(self, index: int) -> None:
        """Recall the stored preset at one-based ``index``."""
        data = await self._async_command({KEY_COMHEAD: CMD_PRESET_SET, "index": index})
        _raise_for_result(data, f"recalling preset {index}")

    async def async_save_preset(self, index: int) -> None:
        """Store the current routing into the preset at one-based ``index``."""
        data = await self._async_command({KEY_COMHEAD: CMD_PRESET_SAVE, "index": index})
        _raise_for_result(data, f"saving preset {index}")

    async def async_set_output_enabled(self, output: int, *, enabled: bool) -> None:
        """Enable or disable the stream on a one-based output."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_TX_STREAM, "out": [output, int(enabled)]}
        )
        _raise_for_result(data, f"setting stream on output {output}")

    async def async_set_audio_muted(self, output: int, *, muted: bool) -> None:
        """Mute or unmute the audio on a one-based output."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_AUDIO_MUTE, "mute": [output, int(muted)]}
        )
        _raise_for_result(data, f"setting audio mute on output {output}")

    async def async_set_hdcp_mode(self, output: int, mode: int) -> None:
        """Set the HDCP mode on a one-based output. See HDCP_MODES."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_TX_HDCP, "hdcp": [output, mode]}
        )
        _raise_for_result(data, f"setting HDCP mode on output {output}")

    async def async_set_scaler_mode(self, output: int, mode: int) -> None:
        """Set the scaler mode on a one-based output. See SCALER_MODES."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_SCALER, "scaler": [output, mode]}
        )
        _raise_for_result(data, f"setting scaler mode on output {output}")

    async def async_set_arc(self, output: int, *, enabled: bool) -> None:
        """Enable or disable ARC on a one-based output."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_ARC, "arc": [output, int(enabled)]}
        )
        _raise_for_result(data, f"setting ARC on output {output}")

    async def async_set_edid(self, source: int, profile: int) -> None:
        """Set the EDID profile on a one-based input. See EDID_PROFILES."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_EDID, "edid": [source, profile]}
        )
        _raise_for_result(data, f"setting EDID on input {source}")

    async def async_set_panel_locked(self, *, locked: bool) -> None:
        """Lock or unlock the front panel buttons."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_PANEL_LOCK, "lock": int(locked)}
        )
        _raise_for_result(data, "setting the panel lock")

    async def async_send_cec(
        self, *, object_type: int, port_mask: list[int], command: int
    ) -> None:
        """Send a CEC command to the ports set in ``port_mask``.

        The matrix goes briefly unresponsive afterwards, which is why every
        command on this client is serialised behind one lock.
        """
        data = await self._async_command(
            {
                KEY_COMHEAD: CMD_CEC_COMMAND,
                "object": object_type,
                "port": port_mask,
                "index": command,
            }
        )
        _raise_for_result(data, f"sending CEC command {command}")

    async def async_set_beep(self, *, enabled: bool) -> None:
        """Turn the front panel beeper on or off."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_BEEP, "beep": int(enabled)}
        )
        _raise_for_result(data, "setting the beeper")


def _raise_for_result(data: dict[str, Any], action: str) -> None:
    """Raise when the firmware reports a command as failed."""
    if data.get("result") != 1:
        raise MatrixResponseError(f"Matrix refused {action}: {data}")


def _bool_list(value: Any, size: int) -> list[bool]:
    """Coerce a firmware array into bools, trimmed to the real port count."""
    return [bool(item) for item in _int_list(value)[:size]]


def _int_list(value: Any) -> list[int]:
    """Coerce a firmware array into ints, dropping anything unparsable."""
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _str_list(value: Any) -> list[str]:
    """Coerce a firmware array into stripped strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value]
