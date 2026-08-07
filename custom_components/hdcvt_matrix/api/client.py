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
from types import TracebackType
from typing import Any, Protocol

import aiohttp

from .commands import (
    CGI_INSTR,
    CMD_CEC_COMMAND,
    CMD_EXT_AUDIO_SWITCH,
    CMD_GET_EXT_AUDIO,
    CMD_GET_INPUT_STATUS,
    CMD_GET_NETWORK,
    CMD_GET_OUTPUT_STATUS,
    CMD_GET_STATUS,
    CMD_GET_SYSTEM_STATUS,
    CMD_GET_VIDEO_STATUS,
    CMD_LOGIN,
    CMD_PRESET_CLEAR,
    CMD_PRESET_NAME,
    CMD_PRESET_SAVE,
    CMD_PRESET_SET,
    CMD_REBOOT,
    CMD_SET_ARC,
    CMD_SET_AUDIO_MUTE,
    CMD_SET_BAUDRATE,
    CMD_SET_BEEP,
    CMD_SET_EDID,
    CMD_SET_EXT_AUDIO_MODE,
    CMD_SET_EXT_AUDIO_OUT,
    CMD_SET_INPUT_NAME,
    CMD_SET_LCD_ON_TIME,
    CMD_SET_OUTPUT_NAME,
    CMD_SET_PANEL_LOCK,
    CMD_SET_POWER,
    CMD_SET_SCALER,
    CMD_TX_HDCP,
    CMD_TX_STREAM,
    CMD_VIDEO_SWITCH,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    KEY_COMHEAD,
    READ_ATTEMPTS,
    READ_RETRY_DELAY,
)
from .exceptions import (
    MatrixAuthError,
    MatrixConnectionError,
    MatrixError,
    MatrixResponseError,
)
from .models import MatrixInfo, MatrixState

_LOGGER = logging.getLogger(__name__)


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
        audio = await self._async_read({KEY_COMHEAD: CMD_GET_EXT_AUDIO})

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
            ext_audio_mode=int(audio.get("mode", 0)),
            ext_audio_routes=_int_list(audio.get("allsource")),
            ext_audio_enabled=[bool(v) for v in _int_list(audio.get("allout"))],
            ext_audio_output_names=_str_list(audio.get("alloutputname")),
            panel_locked=bool(system.get("lock", 0)),
            beep_enabled=bool(system.get("beep", 0)),
            baud_rate=int(system.get("baudrate", 0)),
            lcd_on_time=int(system.get("mode", 0)),
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

    async def async_set_ext_audio_route(self, output: int, source: int) -> None:
        """Route a one-based input to a one-based de-embedded audio output."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_EXT_AUDIO_SWITCH, "source": [output, source]}
        )
        _raise_for_result(data, f"routing audio {source} to audio output {output}")

    async def async_set_ext_audio_enabled(self, output: int, *, enabled: bool) -> None:
        """Enable or disable a one-based de-embedded audio output."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_EXT_AUDIO_OUT, "out": [output, int(enabled)]}
        )
        _raise_for_result(data, f"setting audio output {output}")

    async def async_set_ext_audio_mode(self, mode: int) -> None:
        """Set how the de-embedded audio outputs are driven."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_EXT_AUDIO_MODE, "mode": mode}
        )
        _raise_for_result(data, "setting the audio mode")

    async def async_clear_preset(self, index: int) -> None:
        """Empty the preset at one-based ``index``."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_PRESET_CLEAR, "index": index}
        )
        _raise_for_result(data, f"clearing preset {index}")

    async def async_set_preset_name(self, index: int, name: str) -> None:
        """Rename the preset at one-based ``index``."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_PRESET_NAME, "index": index, "name": name}
        )
        _raise_for_result(data, f"renaming preset {index}")

    async def async_set_input_name(self, source: int, name: str) -> None:
        """Rename a one-based input."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_INPUT_NAME, "name": name, "index": source}
        )
        _raise_for_result(data, f"renaming input {source}")

    async def async_set_output_name(self, output: int, name: str) -> None:
        """Rename a one-based output."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_OUTPUT_NAME, "name": name, "index": output}
        )
        _raise_for_result(data, f"renaming output {output}")

    async def async_set_baud_rate(self, rate: int) -> None:
        """Set the RS-232 rate on the serial control port. See BAUD_RATES."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_BAUDRATE, "baudrate": rate}
        )
        _raise_for_result(data, "setting the baud rate")

    async def async_set_lcd_on_time(self, value: int) -> None:
        """Set the front panel backlight timeout. See LCD_ON_TIMES."""
        data = await self._async_command(
            {KEY_COMHEAD: CMD_SET_LCD_ON_TIME, "lcd on time": value}
        )
        _raise_for_result(data, "setting the LCD timeout")

    async def async_reboot(self) -> None:
        """Restart the matrix.

        Takes it off the network for roughly ten seconds, so the next few
        polls will fail and the entities go unavailable until it is back.
        """
        data = await self._async_command({KEY_COMHEAD: CMD_REBOOT, "reboot": 1})
        _raise_for_result(data, "rebooting")

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
