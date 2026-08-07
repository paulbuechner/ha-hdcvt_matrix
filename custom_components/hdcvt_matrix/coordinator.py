"""Polling coordinator for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    HdcvtMatrixClient,
    MatrixAuthError,
    MatrixError,
    MatrixInfo,
    MatrixState,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HdcvtMatrixCoordinator(DataUpdateCoordinator[MatrixState]):
    """Poll a single matrix and share the result across its entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HdcvtMatrixClient,
        info: MatrixInfo,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.info = info
        # The firmware reports preset names but never says which one is active,
        # and offers no way to read a preset's stored routing back. So the only
        # preset we can honestly report is one we applied ourselves; before
        # that, and after a restart, the answer is "unknown".
        self.active_preset: int | None = None

    async def _async_update_data(self) -> MatrixState:
        """Fetch the current matrix state."""
        try:
            return await self.client.async_get_state()
        except MatrixAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MatrixError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_write(
        self, action: Awaitable[None], describe: str, apply: Callable[[], None] | None
    ) -> None:
        """Send one command, then optimistically reflect it and re-read.

        The matrix can take seconds to settle and may not answer during a
        transition, so entities show the new value immediately and the
        debounced refresh confirms it.
        """
        try:
            await action
        except MatrixAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MatrixError as err:
            raise HomeAssistantError(f"Could not {describe}: {err}") from err

        if apply is not None and self.data is not None:
            apply()
            self.async_update_listeners()
        await self.async_request_refresh()

    async def async_set_power(self, *, on: bool) -> None:
        """Switch the matrix on or into standby."""

        def apply() -> None:
            self.data.power = on

        await self._async_write(
            self.client.async_set_power(on=on),
            f"switch the matrix {'on' if on else 'off'}",
            apply,
        )

    async def async_set_route(self, output: int, source: int) -> None:
        """Route a one-based input to a one-based output."""

        def apply() -> None:
            if output <= len(self.data.routes):
                self.data.routes[output - 1] = source

        await self._async_write(
            self.client.async_set_route(output, source),
            f"route input {source} to output {output}",
            apply,
        )

    async def async_set_output_enabled(self, output: int, *, enabled: bool) -> None:
        """Enable or disable the stream on a one-based output."""

        def apply() -> None:
            if output <= len(self.data.output_enabled):
                self.data.output_enabled[output - 1] = enabled

        await self._async_write(
            self.client.async_set_output_enabled(output, enabled=enabled),
            f"set the stream on output {output}",
            apply,
        )

    async def async_set_audio_muted(self, output: int, *, muted: bool) -> None:
        """Mute or unmute the audio on a one-based output."""

        def apply() -> None:
            if output <= len(self.data.audio_muted):
                self.data.audio_muted[output - 1] = muted

        await self._async_write(
            self.client.async_set_audio_muted(output, muted=muted),
            f"set audio mute on output {output}",
            apply,
        )

    async def async_save_preset(self, index: int) -> None:
        """Store the current routing into a one-based preset slot."""
        await self._async_write(
            self.client.async_save_preset(index), f"save preset {index}", None
        )

    async def async_apply_preset(self, index: int) -> None:
        """Recall a preset and remember it as the active one."""

        def apply() -> None:
            self.active_preset = index

        await self._async_write(
            self.client.async_apply_preset(index), f"recall preset {index}", apply
        )
