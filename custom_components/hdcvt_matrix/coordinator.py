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
    CEC_OBJECT_INPUT,
    CEC_OBJECT_OUTPUT,
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

    async def async_set_hdcp_mode(self, output: int, mode: int) -> None:
        """Set the HDCP mode on a one-based output."""

        def apply() -> None:
            if output <= len(self.data.hdcp_modes):
                self.data.hdcp_modes[output - 1] = mode

        await self._async_write(
            self.client.async_set_hdcp_mode(output, mode),
            f"set the HDCP mode on output {output}",
            apply,
        )

    async def async_set_scaler_mode(self, output: int, mode: int) -> None:
        """Set the scaler mode on a one-based output."""

        def apply() -> None:
            if output <= len(self.data.scaler_modes):
                self.data.scaler_modes[output - 1] = mode

        await self._async_write(
            self.client.async_set_scaler_mode(output, mode),
            f"set the scaler mode on output {output}",
            apply,
        )

    async def async_set_arc(self, output: int, *, enabled: bool) -> None:
        """Enable or disable ARC on a one-based output."""

        def apply() -> None:
            if output <= len(self.data.arc_enabled):
                self.data.arc_enabled[output - 1] = enabled

        await self._async_write(
            self.client.async_set_arc(output, enabled=enabled),
            f"set ARC on output {output}",
            apply,
        )

    async def async_set_edid(self, source: int, profile: int) -> None:
        """Set the EDID profile on a one-based input."""

        def apply() -> None:
            if source <= len(self.data.input_edids):
                self.data.input_edids[source - 1] = profile

        await self._async_write(
            self.client.async_set_edid(source, profile),
            f"set the EDID on input {source}",
            apply,
        )

    async def async_set_panel_locked(self, *, locked: bool) -> None:
        """Lock or unlock the front panel."""

        def apply() -> None:
            self.data.panel_locked = locked

        await self._async_write(
            self.client.async_set_panel_locked(locked=locked),
            "set the panel lock",
            apply,
        )

    async def async_set_beep(self, *, enabled: bool) -> None:
        """Turn the front panel beeper on or off."""

        def apply() -> None:
            self.data.beep_enabled = enabled

        await self._async_write(
            self.client.async_set_beep(enabled=enabled), "set the beeper", apply
        )

    async def async_send_output_cec(self, output: int, command: int) -> None:
        """Send a CEC command to the display on a one-based output."""
        mask = [
            1 if port == output - 1 else 0 for port in range(self.data.output_count)
        ]
        await self._async_write(
            self.client.async_send_cec(
                object_type=CEC_OBJECT_OUTPUT, port_mask=mask, command=command
            ),
            f"send a CEC command to output {output}",
            # Nothing to reflect: CEC is fire and forget, and the matrix cannot
            # report whether the display acted on it.
            None,
        )

    async def async_set_ext_audio_route(self, output: int, source: int) -> None:
        """Route an input to a de-embedded audio output."""

        def apply() -> None:
            if output <= len(self.data.ext_audio_routes):
                self.data.ext_audio_routes[output - 1] = source

        await self._async_write(
            self.client.async_set_ext_audio_route(output, source),
            f"route audio {source} to audio output {output}",
            apply,
        )

    async def async_set_ext_audio_enabled(self, output: int, *, enabled: bool) -> None:
        """Enable or disable a de-embedded audio output."""

        def apply() -> None:
            if output <= len(self.data.ext_audio_enabled):
                self.data.ext_audio_enabled[output - 1] = enabled

        await self._async_write(
            self.client.async_set_ext_audio_enabled(output, enabled=enabled),
            f"set audio output {output}",
            apply,
        )

    async def async_set_ext_audio_mode(self, mode: int) -> None:
        """Set how the de-embedded audio outputs are driven."""

        def apply() -> None:
            self.data.ext_audio_mode = mode

        await self._async_write(
            self.client.async_set_ext_audio_mode(mode), "set the audio mode", apply
        )

    async def async_send_input_cec(self, source: int, command: int) -> None:
        """Send a CEC command to the device on a one-based input."""
        mask = [1 if port == source - 1 else 0 for port in range(self.data.input_count)]
        await self._async_write(
            self.client.async_send_cec(
                object_type=CEC_OBJECT_INPUT, port_mask=mask, command=command
            ),
            f"send a CEC command to input {source}",
            None,
        )

    async def async_clear_preset(self, index: int) -> None:
        """Empty a preset slot."""
        await self._async_write(
            self.client.async_clear_preset(index), f"clear preset {index}", None
        )

    async def async_rename(self, kind: str, index: int, name: str) -> None:
        """Rename an input, an output or a preset.

        Port names feed entity names, so a rename here shows up in Home
        Assistant on the next refresh.
        """
        call = {
            "input": self.client.async_set_input_name,
            "output": self.client.async_set_output_name,
            "preset": self.client.async_set_preset_name,
        }[kind]

        def apply() -> None:
            names = {
                "input": self.data.input_names,
                "output": self.data.output_names,
                "preset": self.data.preset_names,
            }[kind]
            if index <= len(names):
                names[index - 1] = name

        await self._async_write(call(index, name), f"rename {kind} {index}", apply)

    async def async_reboot(self) -> None:
        """Restart the matrix."""
        await self._async_write(self.client.async_reboot(), "reboot the matrix", None)

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
