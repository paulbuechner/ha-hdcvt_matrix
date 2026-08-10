"""Tests for the telnet CLI client."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.hdcvt_matrix.api.exceptions import (
    MatrixConnectionError,
    MatrixResponseError,
)
from custom_components.hdcvt_matrix.api.telnet import CMD_NET_REBOOT, MatrixTelnetClient

HOST = "192.168.10.60"

# What the module sends on connect: telnet IAC negotiation, then the banner.
BANNER = (
    b"\xff\xfb\x03\xff\xfc\x01\xff\xfe\x01"
    b"****************welcome **************\r\n"
    b"            fw version :v1.00.19        \r\n"
    b"**************************************\r\n"
    b"\r\n"
)


class FakeWriter:
    """The slice of ``asyncio.StreamWriter`` the client touches."""

    def __init__(self) -> None:
        """Start with nothing written and the connection open."""
        self.written = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        """Collect outgoing bytes."""
        self.written += data

    async def drain(self) -> None:
        """Pretend the buffer flushed."""

    def close(self) -> None:
        """Record the close."""
        self.closed = True

    async def wait_closed(self) -> None:
        """Pretend the transport shut down."""


def make_client(
    reply: bytes,
    *,
    connect_exc: Exception | None = None,
    read_exc: Exception | None = None,
) -> tuple[MatrixTelnetClient, FakeWriter]:
    """Build a client whose connection replays a canned CLI exchange."""
    writer = FakeWriter()

    async def opener(
        host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if connect_exc is not None:
            raise connect_exc
        reader = asyncio.StreamReader()
        if read_exc is not None:
            # set_exception makes every read raise, like a connection that
            # died before the module said anything.
            reader.set_exception(read_exc)
        else:
            reader.feed_data(BANNER + reply)
            reader.feed_eof()
        # The fake covers exactly the surface the client uses.
        return reader, writer  # type: ignore[return-value]

    client = MatrixTelnetClient(HOST, opener=opener)
    return client, writer


async def test_reply_is_stripped_of_banner_and_echo() -> None:
    """Only the answer comes back: no IAC bytes, no banner, no echo."""
    client, writer = make_client(b"r type!\r\n8x8 hdmi2.1 matrix\r\n")

    reply = await client.async_command("r type!")

    assert reply == "8x8 hdmi2.1 matrix"
    assert writer.written == b"r type!\r\n"
    assert writer.closed


async def test_e00_reads_as_a_rejection() -> None:
    """The CLI's bare E00 must surface as an error, not as a reply."""
    client, _ = make_client(b"r bogus!\r\nE00\r\n")

    with pytest.raises(MatrixResponseError):
        await client.async_command("r bogus!")


async def test_connection_refused_is_wrapped() -> None:
    """Socket errors surface as the integration's connection error."""
    client, _ = make_client(b"", connect_exc=ConnectionRefusedError("refused"))

    with pytest.raises(MatrixConnectionError):
        await client.async_command("r type!")


async def test_net_reboot_survives_the_module_going_down() -> None:
    """The module reboots out from under the connection; that is success."""
    client, writer = make_client(b"", read_exc=ConnectionResetError("gone"))

    await client.async_net_reboot()

    assert writer.written == CMD_NET_REBOOT.encode() + b"\r\n"
    assert writer.closed


async def test_a_dropped_read_still_fails_normal_commands() -> None:
    """Only tolerate_drop commands may treat a dead connection as success."""
    client, _ = make_client(b"", read_exc=ConnectionResetError("gone"))

    with pytest.raises(MatrixConnectionError):
        await client.async_command("r type!")


async def test_a_saved_preset_parses_into_routes() -> None:
    """Each outputN->inputM line lands at its output's position."""
    reply = b"r preset 2!\r\n" + b"".join(
        f"output{output}->input{source}\r\n".encode()
        for output, source in enumerate([7, 8, 1, 2, 3, 4, 5, 6], start=1)
    )
    client, _ = make_client(reply)

    assert await client.async_read_preset(2) == [7, 8, 1, 2, 3, 4, 5, 6]


async def test_an_empty_preset_reads_as_none() -> None:
    """The firmware's 'is none' phrasing means an empty slot, not an error."""
    client, _ = make_client(b"r preset 8!\r\npreset 8 is none,please save a preset\r\n")

    assert await client.async_read_preset(8) is None


async def test_a_garbled_preset_raises() -> None:
    """Half a crosspoint table must fail loudly, not restore half a preset."""
    client, _ = make_client(b"r preset 1!\r\noutput1->input7\r\noutput5->input2\r\n")

    with pytest.raises(MatrixResponseError):
        await client.async_read_preset(1)
