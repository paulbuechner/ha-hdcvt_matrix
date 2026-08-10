"""Preset saving for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HdcvtMatrixConfigEntry
from .api import (
    CEC_OUTPUT_MUTE,
    CEC_OUTPUT_POWER_OFF,
    CEC_OUTPUT_POWER_ON,
    CEC_OUTPUT_VOLUME_DOWN,
    CEC_OUTPUT_VOLUME_UP,
)
from .const import FEATURE_CEC, FEATURE_PRESET_MANAGEMENT, FEATURE_SYSTEM
from .coordinator import HdcvtMatrixCoordinator
from .entity import HdcvtMatrixEntity, HdcvtMatrixPortEntity
from .features import async_prune, enabled

PARALLEL_UPDATES = 0


# Home Assistant fixes this signature: it awaits the callback and passes `hass`
# whether or not a platform needs either. Neither is ours to change.
async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,  # NOSONAR
    entry: HdcvtMatrixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up reboot, preset save buttons and CEC display power per output."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = []

    if enabled(entry, FEATURE_SYSTEM):
        entities.append(HdcvtMatrixReboot(coordinator))
        entities.append(HdcvtMatrixNetReboot(coordinator))

    if enabled(entry, FEATURE_PRESET_MANAGEMENT):
        entities.append(HdcvtMatrixBackupPresets(coordinator))
        entities.append(HdcvtMatrixRestorePresets(coordinator))
        for index in range(1, len(coordinator.data.preset_names) + 1):
            entities.append(HdcvtMatrixSavePreset(coordinator, index))
            entities.append(HdcvtMatrixClearPreset(coordinator, index))

    if enabled(entry, FEATURE_CEC):
        for output in range(1, coordinator.data.output_count + 1):
            entities.append(HdcvtMatrixDisplayPower(coordinator, output, on=True))
            entities.append(HdcvtMatrixDisplayPower(coordinator, output, on=False))
            for key, command in (
                ("volume_up", CEC_OUTPUT_VOLUME_UP),
                ("volume_down", CEC_OUTPUT_VOLUME_DOWN),
                ("mute", CEC_OUTPUT_MUTE),
            ):
                entities.append(
                    HdcvtMatrixDisplayCec(coordinator, output, key, command)
                )

    async_prune(hass, entry, "button", (e.unique_id or "" for e in entities))
    async_add_entities(entities)


class HdcvtMatrixDisplayPower(HdcvtMatrixPortEntity, ButtonEntity):
    """Power a display on or off over CEC.

    A button rather than a switch because CEC here is one-way: the matrix can
    send the command but cannot report whether the display obeyed, or what
    state it is in.
    """

    def __init__(
        self, coordinator: HdcvtMatrixCoordinator, output: int, *, on: bool
    ) -> None:
        """Initialise the CEC power button for a one-based output."""
        action = "on" if on else "off"
        super().__init__(
            coordinator, f"output_{output}_display_{action}", "output", output
        )
        self._command = CEC_OUTPUT_POWER_ON if on else CEC_OUTPUT_POWER_OFF
        self._attr_translation_key = f"display_{action}"

    async def async_press(self) -> None:
        """Send the CEC power command to this output's display."""
        await self.coordinator.async_send_output_cec(self._port, self._command)


class HdcvtMatrixSavePreset(HdcvtMatrixPortEntity, ButtonEntity):
    """Overwrite one preset with the routing currently in effect."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "save_preset"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, index: int) -> None:
        """Initialise the button for a one-based preset slot."""
        super().__init__(coordinator, f"save_preset_{index}", "preset", index)

    async def async_press(self) -> None:
        """Store the current routing into this preset."""
        await self.coordinator.async_save_preset(self._port)


class HdcvtMatrixReboot(HdcvtMatrixEntity, ButtonEntity):
    """Restart the matrix.

    Opt-in like the rest, which doubles as the safety catch: a stray tap on a
    dashboard should not drop every display for ten seconds.
    """

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reboot"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the reboot button."""
        super().__init__(coordinator, "reboot")

    async def async_press(self) -> None:
        """Restart the matrix."""
        await self.coordinator.async_reboot()


class HdcvtMatrixBackupPresets(HdcvtMatrixEntity, ButtonEntity):
    """Snapshot every saved preset into Home Assistant's storage.

    Reads the slots over the telnet CLI, the only channel that can. Saves
    made through Home Assistant keep the backup fresh on their own; this
    button catches up after changes made in the device web UI.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "backup_presets"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the backup button."""
        super().__init__(coordinator, "backup_presets")

    async def async_press(self) -> None:
        """Read all slots and persist them."""
        await self.coordinator.async_snapshot_presets()


class HdcvtMatrixRestorePresets(HdcvtMatrixEntity, ButtonEntity):
    """Rebuild the device's presets from the stored backup.

    The one recovery path after a firmware flash wipes the slots. The
    firmware can only save a preset from live routing, so displays flick
    through the scenarios while the slots are rebuilt.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "restore_presets"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the restore button."""
        super().__init__(coordinator, "restore_presets")

    async def async_press(self) -> None:
        """Apply, save and rename every backed-up slot."""
        await self.coordinator.async_restore_presets()


class HdcvtMatrixNetReboot(HdcvtMatrixEntity, ButtonEntity):
    """Restart the matrix's IP module.

    The one control with no JSON equivalent, so it goes over the telnet CLI.
    Rescues a wedged web interface without dropping a single video route;
    the module is back within seconds and the next poll reconnects.
    """

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "net_reboot"

    def __init__(self, coordinator: HdcvtMatrixCoordinator) -> None:
        """Initialise the network module reboot button."""
        super().__init__(coordinator, "net_reboot")

    async def async_press(self) -> None:
        """Restart the IP module."""
        await self.coordinator.async_reboot_network()


class HdcvtMatrixClearPreset(HdcvtMatrixPortEntity, ButtonEntity):
    """Empty one preset slot."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "clear_preset"

    def __init__(self, coordinator: HdcvtMatrixCoordinator, index: int) -> None:
        """Initialise the clear button for a one-based preset slot."""
        super().__init__(coordinator, f"clear_preset_{index}", "preset", index)

    async def async_press(self) -> None:
        """Empty this preset."""
        await self.coordinator.async_clear_preset(self._port)


class HdcvtMatrixDisplayCec(HdcvtMatrixPortEntity, ButtonEntity):
    """Send a non-power CEC command to one output's display."""

    def __init__(
        self,
        coordinator: HdcvtMatrixCoordinator,
        output: int,
        key: str,
        command: int,
    ) -> None:
        """Initialise a CEC button for a one-based output."""
        super().__init__(
            coordinator, f"output_{output}_display_{key}", "output", output
        )
        self._command = command
        self._attr_translation_key = f"display_{key}"

    async def async_press(self) -> None:
        """Send the CEC command."""
        await self.coordinator.async_send_output_cec(self._port, self._command)
