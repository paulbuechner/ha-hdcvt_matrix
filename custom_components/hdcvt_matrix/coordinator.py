"""Polling coordinator for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
import logging
import time
from typing import Any, Final, TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    CEC_OBJECT_INPUT,
    CEC_OBJECT_OUTPUT,
    HdcvtMatrixClient,
    MatrixAuthError,
    MatrixError,
    MatrixInfo,
    MatrixState,
    MatrixTelnetClient,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

_BACKUP_STORAGE_VERSION: Final = 1

# A preset recall takes 3-5 s to settle on the reference unit, during which
# the matrix is switching every output. Recalls inside this window are
# refused rather than queued.
PRESET_APPLY_COOLDOWN: Final = 5.0


class PresetBackupSlot(TypedDict):
    """One preset as persisted: its name and its stored routing."""

    name: str
    routes: list[int]


class HdcvtMatrixCoordinator(DataUpdateCoordinator[MatrixState]):
    """Poll a single matrix and share the result across its entities."""

    # Restated from the generic base. Type checkers that do not follow
    # DataUpdateCoordinator[MatrixState] through to `.data` otherwise infer Any
    # here, which then propagates into every `_value()` call in the platforms.
    data: MatrixState

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HdcvtMatrixClient,
        info: MatrixInfo,
        telnet: MatrixTelnetClient | None = None,
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
        # Same host, different protocol: the CLI carries the few commands the
        # JSON API lacks. Polling and everything else stays on HTTP.
        self.telnet = telnet or MatrixTelnetClient(client.host)
        self.info = info
        # The firmware never reports which preset is active, so this is
        # derived: each poll matches the live routing against the backed-up
        # slot contents, which costs nothing extra because both are already
        # to hand. That sees recalls made on the front panel or in the web
        # UI, and drops to "unknown" once a single route is changed by hand.
        #
        # Without a backup there is nothing to match, so the record of what
        # we applied ourselves remains, and it also breaks ties when two
        # slots hold the same routing. It is persisted rather than merely
        # held here: a reload while the matrix is unreachable used to lose
        # it, the entity's last state then being "unavailable".
        self.active_preset: int | None = None
        # Preset contents and EDID selections survive here, because they do
        # not survive on the device: flashing firmware wipes the slots and
        # resets every input's EDID, and only the telnet CLI can read a slot
        # back at all.
        self._backup_store: Store[dict[str, Any]] = Store(
            hass, _BACKUP_STORAGE_VERSION, f"{DOMAIN}.preset_backup_{entry.entry_id}"
        )
        self.preset_backup: dict[int, PresetBackupSlot] = {}
        self.edid_backup: dict[int, int] = {}
        self.preset_backup_saved_at: str | None = None
        self.preset_backup_drift: list[int] = []
        self.edid_backup_drift: list[int] = []
        self._preset_applied_at: float | None = None

    async def _async_update_data(self) -> MatrixState:
        """Fetch the current matrix state."""
        try:
            state = await self.client.async_get_state()
        except MatrixAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MatrixError as err:
            raise UpdateFailed(str(err)) from err

        # Defensive, and not reached on the reference HDP-MXC88A: probing it
        # in standby showed every table still reported, with only `power`
        # flipping to 0. Kept because this firmware is resold under several
        # brands and a variant that blanks its tables would otherwise make
        # every entity go unknown at once on each power change.
        if not state.output_names and self.data is not None:
            return replace(self.data, power=state.power)

        self._refresh_backup_drift(state)
        self._refresh_active_preset(state)
        return state

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
        """Set the EDID profile on a one-based input.

        A backed-up input follows along, so a deliberate change through Home
        Assistant does not read as drift. Changes made in the device web UI
        still need the backup button.
        """

        def apply() -> None:
            if source <= len(self.data.input_edids):
                self.data.input_edids[source - 1] = profile

        await self._async_write(
            self.client.async_set_edid(source, profile),
            f"set the EDID on input {source}",
            apply,
        )
        if source in self.edid_backup:
            self.edid_backup[source] = profile
            await self._async_persist_backup()

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
        """Empty a preset slot, and drop it from the backup."""
        await self._async_write(
            self.client.async_clear_preset(index), f"clear preset {index}", None
        )
        if self.preset_backup.pop(index, None) is not None:
            await self._async_persist_backup()

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

        # Keep the backup's name in step, or the drift sensor would read a
        # deliberate rename as a wiped device.
        if kind == "preset" and index in self.preset_backup:
            self.preset_backup[index]["name"] = name
            await self._async_persist_backup()

    async def async_set_baud_rate(self, rate: int) -> None:
        """Set the RS-232 rate on the serial control port."""

        def apply() -> None:
            self.data.baud_rate = rate

        await self._async_write(
            self.client.async_set_baud_rate(rate), "set the baud rate", apply
        )

    async def async_set_lcd_on_time(self, value: int) -> None:
        """Set the front panel backlight timeout."""

        def apply() -> None:
            self.data.lcd_on_time = value

        await self._async_write(
            self.client.async_set_lcd_on_time(value), "set the LCD timeout", apply
        )

    async def async_reboot(self) -> None:
        """Restart the matrix."""
        await self._async_write(self.client.async_reboot(), "reboot the matrix", None)

    async def async_reboot_network(self) -> None:
        """Restart the IP module; routing and video are unaffected.

        The refresh scheduled afterwards may catch the module mid-restart and
        fail once; the following poll reconnects.
        """
        await self._async_write(
            self.telnet.async_net_reboot(), "reboot the network module", None
        )

    async def async_save_preset(self, index: int) -> None:
        """Store the current routing into a one-based preset slot.

        The backup learns the slot at the same time: a save through Home
        Assistant snapshots the routes we already hold, no telnet read
        needed. Saves made in the device web UI still need the backup
        button.
        """
        await self._async_write(
            self.client.async_save_preset(index), f"save preset {index}", None
        )
        if index <= len(self.data.preset_names):
            self.preset_backup[index] = {
                "name": self.data.preset_names[index - 1],
                "routes": list(self.data.routes),
            }
            await self._async_persist_backup()

    async def async_apply_preset(self, index: int) -> None:
        """Recall a preset and remember it as the active one.

        The matrix takes 3-5 s to settle after a recall, switching every
        output as it goes; a second recall inside that window lands on a
        device still mid-transition. Refused with an error rather than
        queued, so the user sees why nothing happened.
        """
        now = time.monotonic()
        if (
            self._preset_applied_at is not None
            and now - self._preset_applied_at < PRESET_APPLY_COOLDOWN
        ):
            remaining = PRESET_APPLY_COOLDOWN - (now - self._preset_applied_at)
            raise HomeAssistantError(
                f"The matrix is still applying the previous preset; "
                f"try again in {max(1, round(remaining))} seconds"
            )
        # Armed before the write goes out, or two quick recalls would both
        # pass the check and queue up behind the client's lock.
        self._preset_applied_at = now

        def apply() -> None:
            self.active_preset = index

        try:
            await self._async_write(
                self.client.async_apply_preset(index), f"recall preset {index}", apply
            )
        except Exception:
            # A recall that never happened should not lock the user out.
            self._preset_applied_at = None
            raise
        await self._async_persist_active_preset()

    def _refresh_active_preset(self, state: MatrixState) -> None:
        """Derive the active preset from the routing the matrix reports.

        A slot is active when the live routing is exactly its stored
        routing. The remembered slot wins when it still matches, so two
        slots holding the same routing do not make the reading flip about;
        otherwise the lowest matching slot is taken.

        With no backup there is nothing to compare, so whatever we last
        applied stands. Ignored while the matrix is off, where the routing
        is still reported but recalls have not been applied to it.
        """
        if not self.preset_backup or not state.power or not state.routes:
            return

        routes = list(state.routes)
        matches = [
            slot
            for slot, backup in sorted(self.preset_backup.items())
            if backup["routes"] == routes
        ]
        if self.active_preset in matches:
            return
        self.active_preset = matches[0] if matches else None

    async def async_adopt_active_preset(self, index: int) -> None:
        """Take an active preset recovered elsewhere, and persist it."""
        self.active_preset = index
        await self._async_persist_active_preset()

    async def async_load_preset_backup(self) -> None:
        """Load the preset backup persisted for this entry."""
        stored = await self._backup_store.async_load()
        if not stored:
            return
        self.preset_backup = {
            int(slot): value for slot, value in stored.get("presets", {}).items()
        }
        self.edid_backup = {
            int(source): value
            for source, value in stored.get("input_edids", {}).items()
        }
        self.preset_backup_saved_at = stored.get("saved_at")
        active = stored.get("active_preset")
        self.active_preset = int(active) if active is not None else None
        self._refresh_backup_drift()

    def _refresh_backup_drift(self, state: MatrixState | None = None) -> None:
        """Recompute what no longer matches the backup.

        Preset names and EDID ids both ride along in every poll for free,
        and a firmware flash — the event this exists to catch — resets both.
        Preset contents are only readable over telnet, so they are
        deliberately not compared on the polling path.
        """
        data = state if state is not None else self.data
        names = data.preset_names if data is not None else []
        edids = data.input_edids if data is not None else []
        self.preset_backup_drift = [
            slot
            for slot, backup in sorted(self.preset_backup.items())
            if slot <= len(names) and names[slot - 1] != backup["name"]
        ]
        self.edid_backup_drift = [
            source
            for source, profile in sorted(self.edid_backup.items())
            if source <= len(edids) and edids[source - 1] != profile
        ]

    def _stored_backup(self) -> dict[str, Any]:
        """Shape the backup for storage."""
        return {
            "saved_at": self.preset_backup_saved_at,
            "active_preset": self.active_preset,
            "presets": {str(slot): value for slot, value in self.preset_backup.items()},
            "input_edids": {
                str(source): value for source, value in self.edid_backup.items()
            },
        }

    async def _async_persist_backup(self) -> None:
        """Write the backup to storage and refresh the drift sensor."""
        self.preset_backup_saved_at = dt_util.utcnow().isoformat()
        await self._backup_store.async_save(self._stored_backup())
        self._refresh_backup_drift()
        self.async_update_listeners()

    async def _async_persist_active_preset(self) -> None:
        """Record which preset was applied, without restamping the backup.

        Kept separate from the backup save so recalling a preset does not
        make an old snapshot look freshly taken.
        """
        await self._backup_store.async_save(self._stored_backup())

    async def async_snapshot_presets(self) -> None:
        """Persist every preset slot and every input's EDID selection.

        Preset contents come over telnet, the only channel that can read
        them; the EDID ids are already in the polled state.
        """
        names = self.data.preset_names
        presets: dict[int, PresetBackupSlot] = {}
        changed: list[int] = []
        try:
            for slot in range(1, len(names) + 1):
                routes = await self.telnet.async_read_preset(slot)
                if routes is None:
                    continue
                presets[slot] = {"name": names[slot - 1], "routes": routes}
                previous = self.preset_backup.get(slot)
                if previous is not None and previous["routes"] != routes:
                    changed.append(slot)
        except MatrixError as err:
            raise HomeAssistantError(f"Could not back up the presets: {err}") from err

        # An all-empty device is what a fresh wipe looks like; overwriting a
        # good backup with that would destroy the one copy worth having.
        if not presets:
            raise HomeAssistantError(
                "The matrix reports no saved presets; nothing was backed up"
            )

        if changed:
            _LOGGER.info(
                "%s: preset %s changed on the device since the last backup",
                self.client.host,
                ", ".join(str(slot) for slot in changed),
            )

        self.preset_backup = presets
        self.edid_backup = {
            source: profile
            for source, profile in enumerate(self.data.input_edids, start=1)
        }
        await self._async_persist_backup()
        # Contents may now match a different slot than before.
        if self.data is not None:
            self._refresh_active_preset(self.data)
            self.async_update_listeners()

    async def _async_verify_slots(self) -> list[int]:
        """Read the backed-up slots back, returning those that do not match.

        Off the polling path: a slot read takes a second or two, which is
        affordable once after a restore and never per poll.
        """
        return [
            slot
            for slot, backup in sorted(self.preset_backup.items())
            if await self.telnet.async_read_preset(slot) != backup["routes"]
        ]

    async def _async_push_backup(self, live: list[int]) -> None:
        """Drive the device through each backed-up slot, then back.

        ``live`` mirrors the device's routing as writes land, so a route
        already in place is skipped: fewer writes, less display flicker.
        """
        original = list(live)

        async def switch(output: int, source: int) -> None:
            if output <= len(live) and live[output - 1] == source:
                return
            await self.client.async_set_route(output, source)
            if output <= len(live):
                live[output - 1] = source

        for slot, backup in sorted(self.preset_backup.items()):
            for output, source in enumerate(backup["routes"], start=1):
                await switch(output, source)
            await self.client.async_save_preset(slot)
            await self.client.async_set_preset_name(slot, backup["name"])
        for output, source in enumerate(original, start=1):
            await switch(output, source)

    async def async_restore_presets(self) -> None:
        """Rebuild the preset slots and EDID selections from the backup.

        The firmware can only save a preset from the live routing, so each
        slot is applied, saved and renamed in turn, and the routing that was
        in effect beforehand is put back at the end. Displays flick through
        the scenarios while this runs; EDID writes follow, and sources
        re-handshake briefly.
        """
        if not self.preset_backup:
            raise HomeAssistantError("There is no preset backup to restore")

        try:
            await self._async_push_backup(list(self.data.routes))
            for source, profile in sorted(self.edid_backup.items()):
                if (
                    source <= len(self.data.input_edids)
                    and self.data.input_edids[source - 1] != profile
                ):
                    await self.client.async_set_edid(source, profile)
            wrong = await self._async_verify_slots()
        except MatrixAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MatrixError as err:
            raise HomeAssistantError(f"Could not restore the presets: {err}") from err

        self._apply_restored_state()
        await self.async_request_refresh()

        if wrong:
            raise HomeAssistantError(
                "Restored, but the matrix did not store "
                f"{'presets' if len(wrong) > 1 else 'preset'} "
                f"{', '.join(str(slot) for slot in wrong)} as expected"
            )

    def _apply_restored_state(self) -> None:
        """Reflect the restored names and EDIDs; the refresh confirms them."""
        for slot, backup in self.preset_backup.items():
            if slot <= len(self.data.preset_names):
                self.data.preset_names[slot - 1] = backup["name"]
        for source, profile in self.edid_backup.items():
            if source <= len(self.data.input_edids):
                self.data.input_edids[source - 1] = profile
        self._refresh_backup_drift()
        self.async_update_listeners()
