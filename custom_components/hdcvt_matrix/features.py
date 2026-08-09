"""Which optional feature groups a config entry has switched on."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CONF_FEATURES
from .registry import entity_reg


def enabled(entry: ConfigEntry, feature: str) -> bool:
    """Whether a feature group is switched on for this entry."""
    return feature in entry.options.get(CONF_FEATURES, [])


@callback
def async_prune(
    hass: HomeAssistant,
    entry: ConfigEntry,
    platform: str,
    keep: Iterable[str],
) -> None:
    """Forget entities this platform no longer creates.

    Turning a feature off has to remove its entities, not leave them behind as
    unavailable ghosts in the registry. Called on every setup, so the registry
    always matches what the current options ask for.
    """
    wanted = set(keep)
    registry = entity_reg(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain == platform and entity.unique_id not in wanted:
            registry.async_remove(entity.entity_id)
