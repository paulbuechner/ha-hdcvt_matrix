"""Which entities a fresh install actually adds.

An 8x8 exposes around ninety entities. Adding them all on setup buries the
handful anyone routinely uses, so everything except core routing ships
disabled and the user opts in. This pins that split, because it is easy to
regress by copying an existing entity class.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.hdcvt_matrix.const import DOMAIN

from .conftest import MAC, SetupIntegration, make_session


@pytest.fixture(autouse=True)
def auto_enable_all_entities() -> None:
    """Override conftest: this module is about the untouched defaults."""
    return


def _by_disabled(hass: HomeAssistant) -> tuple[set[str], set[str]]:
    """Split this integration's registry entries into enabled and disabled."""
    registry = er.async_get(hass)
    enabled: set[str] = set()
    disabled: set[str] = set()
    for entry in registry.entities.values():
        if entry.platform != DOMAIN:
            continue
        key = entry.unique_id.removeprefix(f"{MAC}_")
        (disabled if entry.disabled else enabled).add(key)
    return enabled, disabled


async def test_only_core_routing_is_enabled(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Power, the eight routing selects and preset recall. Nothing else."""
    await setup_integration(make_session())

    enabled, _ = _by_disabled(hass)

    assert enabled == {
        "power",
        "preset",
        *(f"output_{output}" for output in range(1, 9)),
    }


async def test_the_long_tail_is_registered_but_disabled(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Opt-in entities still exist, so enabling one needs no code change."""
    await setup_integration(make_session())

    _, disabled = _by_disabled(hass)

    # A sample across every platform that ships opt-in.
    assert {
        "output_1_hdcp",
        "output_1_scaler",
        "input_1_edid",
        "output_1_stream",
        "output_1_mute",
        "output_1_arc",
        "panel_lock",
        "beep",
        "input_1_signal",
        "output_1_sink",
        "save_preset_1",
        "output_1_display_on",
    } <= disabled


async def test_a_fresh_install_stays_small(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The point of the exercise: ten entities, not ninety."""
    await setup_integration(make_session())

    enabled, disabled = _by_disabled(hass)

    assert len(enabled) == 10
    assert len(disabled) > 60
