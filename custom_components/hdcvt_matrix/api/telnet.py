"""Text-protocol client for the matrix's telnet CLI.

The IP module bridges the MCU's serial command processor to telnet port 23,
unauthenticated like the HTTP API. The dialect is ``s ...!``/``r ...!`` with
``!`` as the terminator; a rejected command answers with a bare ``E00``. Only
commands with no JSON equivalent belong here — everything else stays on the
HTTP client, which is the polled and proven path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
import re
from typing import Final

from .commands import DEFAULT_TIMEOUT
from .exceptions import MatrixConnectionError, MatrixResponseError

DEFAULT_TELNET_PORT: Final = 23

# The one command the JSON API lacks: restart the IP module on its own. The
# matrix keeps switching; the module drops the connection while going down.
CMD_NET_REBOOT: Final = "s net reboot!"

# Telnet IAC negotiation the module sends on connect. It does not insist on
# an answer, so stripping the bytes is all the negotiation needed.
_IAC_RE: Final = re.compile(rb"\xff[\xfb-\xfe].|\xff.")

# The CLI prints its reply in one quick burst; once output pauses this long
# after the first byte, the reply is over. Generous against the sub-second
# gap measured between banner and reply on the reference unit.
_IDLE_WINDOW: Final = 1.0

_ERROR_REPLY: Final = "E00"

# One line per output in a saved preset's reply, e.g. "output3->input1".
_PRESET_ROUTE_RE: Final = re.compile(r"^output(\d+)->input(\d+)$")

# An empty slot answers "preset N is none,please save a preset".
_PRESET_EMPTY: Final = "is none"

type TelnetOpener = Callable[
    [str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]
]


class MatrixTelnetClient:
    """Talk to a single HDCVT matrix over its telnet CLI."""

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_TELNET_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        opener: TelnetOpener | None = None,
    ) -> None:
        """Initialise the client; ``opener`` exists as a seam for tests."""
        self._host = host
        self._port = port
        self._timeout = timeout
        self._opener: TelnetOpener = opener or asyncio.open_connection
        # The module serves a single console; a second session would steal
        # the first one's reply.
        self._lock = asyncio.Lock()

    async def async_net_reboot(self) -> None:
        """Restart the IP module; the connection dying mid-reply is success."""
        await self.async_command(CMD_NET_REBOOT, tolerate_drop=True)

    async def async_read_preset(self, index: int) -> list[int] | None:
        """Read the routing stored in a one-based preset slot.

        Returns the one-based input feeding each output, or None for an
        empty slot. The JSON API cannot read preset contents at all; this
        is the only channel that can.
        """
        reply = await self.async_command(f"r preset {index}!")
        if _PRESET_EMPTY in reply:
            return None

        routes: dict[int, int] = {}
        for line in reply.splitlines():
            match = _PRESET_ROUTE_RE.match(line.strip())
            if match:
                routes[int(match.group(1))] = int(match.group(2))
        if not routes or sorted(routes) != list(range(1, len(routes) + 1)):
            raise MatrixResponseError(
                f"{self._host} returned an unreadable preset {index}: {reply[:120]!r}"
            )
        return [routes[output] for output in sorted(routes)]

    async def async_command(self, command: str, *, tolerate_drop: bool = False) -> str:
        """Send one CLI command and return the reply text.

        ``tolerate_drop`` is for commands that take the connection down with
        them: once the command is on the wire, losing the connection counts
        as success rather than an error.
        """
        async with self._lock:
            try:
                reader, writer = await asyncio.wait_for(
                    self._opener(self._host, self._port), self._timeout
                )
            except TimeoutError as err:
                raise MatrixConnectionError(
                    f"Timed out connecting to the CLI on {self._host}"
                ) from err
            except OSError as err:
                raise MatrixConnectionError(
                    f"Cannot reach the CLI on {self._host}: {err}"
                ) from err

            try:
                try:
                    writer.write(command.encode("ascii") + b"\r\n")
                    await writer.drain()
                    raw = await self._async_read_reply(reader)
                except (TimeoutError, OSError) as err:
                    if not tolerate_drop:
                        raise MatrixConnectionError(
                            f"Lost the CLI on {self._host} during {command!r}: {err}"
                        ) from err
                    raw = b""
            finally:
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()

        reply = self._extract_reply(command, raw)
        if _ERROR_REPLY in reply.split():
            raise MatrixResponseError(f"{self._host} rejected {command!r}")
        return reply

    async def _async_read_reply(self, reader: asyncio.StreamReader) -> bytes:
        """Collect output until it goes quiet, hits EOF, or times out.

        There is no prompt and no length marker, so "quiet" is the only end
        signal the CLI offers: the banner arrives immediately on connect and
        the reply follows within the idle window.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        chunks: list[bytes] = []
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                if chunks:
                    break
                raise TimeoutError(f"no CLI output from {self._host}")
            wait = min(_IDLE_WINDOW, remaining) if chunks else remaining
            try:
                chunk = await asyncio.wait_for(reader.read(1024), wait)
            except TimeoutError:
                if chunks:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def _extract_reply(self, command: str, raw: bytes) -> str:
        """Strip telnet negotiation, the banner and the command echo.

        The echo is the anchor: everything before it is banner. When it is
        missing the connection dropped early, and whatever arrived is
        returned as-is for the caller's best-effort handling.
        """
        text = _IAC_RE.sub(b"", raw).decode("ascii", "replace")
        lines = [line.rstrip("\r") for line in text.split("\n")]
        for index, line in enumerate(lines):
            if line.strip() == command:
                lines = lines[index + 1 :]
                break
        return "\n".join(line for line in lines if line.strip()).strip()
