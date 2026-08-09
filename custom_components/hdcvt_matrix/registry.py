"""Typed accessors for the Home Assistant registries.

Both wrapped calls are synchronous, but PyCharm resolves HA's @singleton to
its async overload and infers a Coroutine, which makes every attribute read
off the result look unresolved. mypy gets it right -- core guards that with
_test_singleton_typing -- and a cast would trip its warn-redundant-casts, so
a suppression scoped to the one tool that is wrong is the honest fix, and it
belongs in one place rather than at every call site.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er


@callback
def entity_reg(hass: HomeAssistant) -> er.EntityRegistry:
    """Return the entity registry."""
    # noinspection PyTypeChecker
    registry: er.EntityRegistry = er.async_get(hass)
    return registry


@callback
def device_reg(hass: HomeAssistant) -> dr.DeviceRegistry:
    """Return the device registry."""
    # noinspection PyTypeChecker
    registry: dr.DeviceRegistry = dr.async_get(hass)
    return registry
