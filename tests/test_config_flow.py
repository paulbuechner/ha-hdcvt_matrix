"""Tests for the HDCVT HDMI Matrix config flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hdcvt_matrix.const import CONF_USE_DEFAULT_CREDENTIALS, DOMAIN

from .conftest import PatchClientsession, make_session

HOST = "192.168.10.60"
MAC = "6C:DF:FB:01:AB:CD"
UNIQUE_ID = "6c:df:fb:01:ab:cd"

# The stock hostname the matrix announces over DHCP.
DHCP_INFO = DhcpServiceInfo(
    ip=HOST,
    hostname="ip-module-abcd",
    macaddress="6cdffb01abcd",
)

# Home Assistant learns hostnames from the router, so a user who renamed the
# lease presents an arbitrary name instead of the stock one.
DHCP_INFO_RENAMED = DhcpServiceInfo(
    ip=HOST,
    hostname="my-matrix-switch",
    macaddress="6cdffb01abcd",
)


def test_dhcp_matcher_does_not_require_a_hostname() -> None:
    """The MAC alone must be enough, for users who renamed the DHCP lease."""
    manifest = json.loads(
        (
            Path(__file__).parents[1]
            / "custom_components"
            / "hdcvt_matrix"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert any(set(matcher) == {"macaddress"} for matcher in manifest["dhcp"])


async def test_user_flow_creates_entry(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """A reachable matrix with good credentials produces an entry keyed by MAC."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: HOST,
                CONF_USE_DEFAULT_CREDENTIALS: False,
                CONF_USERNAME: "admin",
                CONF_PASSWORD: "pw",
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HDP-MXC88A"
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "pw",
    }
    assert result["result"].unique_id == UNIQUE_ID


async def test_user_flow_without_credentials(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """Credentials are optional, because the API answers reads unauthenticated."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USE_DEFAULT_CREDENTIALS: False},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST}


async def test_default_credentials_checkbox_fills_them_in(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """Ticking the box stores the factory pair, so host alone is enough."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    session = make_session()
    with patch_clientsession(session):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USE_DEFAULT_CREDENTIALS: True},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_USERNAME: "Admin",
        CONF_PASSWORD: "admin",
    }
    # The flag is a UI affordance and must not leak into the stored entry.
    assert CONF_USE_DEFAULT_CREDENTIALS not in result["data"]
    assert session.requests[0] == {
        "comhead": "login",
        "user": "Admin",
        "password": "admin",
    }


async def test_default_credentials_checkbox_beats_typed_values(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """The label promises the defaults win, so typed values must not sneak through."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: HOST,
                CONF_USE_DEFAULT_CREDENTIALS: True,
                CONF_USERNAME: "someone",
                CONF_PASSWORD: "else",
            },
        )
        await hass.async_block_till_done()

    assert result["data"][CONF_USERNAME] == "Admin"
    assert result["data"][CONF_PASSWORD] == "admin"


async def test_unticking_uses_typed_credentials(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """With the box clear, whatever was typed is what gets stored."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: HOST,
                CONF_USE_DEFAULT_CREDENTIALS: False,
                CONF_USERNAME: "someone",
                CONF_PASSWORD: "else",
            },
        )
        await hass.async_block_till_done()

    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_USERNAME: "someone",
        CONF_PASSWORD: "else",
    }


@pytest.mark.parametrize(
    ("session_kwargs", "expected"),
    [
        ({"exc": aiohttp.ClientError("down")}, "cannot_connect"),
        ({"login_ok": False}, "invalid_auth"),
        (
            {"overrides": {"get status": "not wait comhead [get status]"}},
            "unsupported_device",
        ),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant,
    patch_clientsession: PatchClientsession,
    session_kwargs: dict[str, Any],
    expected: str,
) -> None:
    """Each failure shows an error and the form stays usable."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch_clientsession(make_session(**session_kwargs)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """The same matrix cannot be added twice, and the host is refreshed."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=UNIQUE_ID, data={CONF_HOST: "192.168.10.99"}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST


async def test_dhcp_discovery_confirms(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """A DHCP lease is verified as a matrix, then asks only for credentials."""
    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=DHCP_INFO
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {"name": "HDP-MXC88A", "host": HOST}

    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "pw"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == HOST
    assert result["result"].unique_id == UNIQUE_ID


async def test_dhcp_discovery_survives_a_renamed_lease(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """Discovery keys off the MAC, so renaming the lease must not break it."""
    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DHCP_INFO_RENAMED,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {"name": "HDP-MXC88A", "host": HOST}


async def test_dhcp_discovery_ignores_non_matrix(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """Something else on that MAC prefix must not be offered as a matrix."""
    with patch_clientsession(
        make_session(overrides={"get status": "<html>router</html>"})
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=DHCP_INFO
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unsupported_device"


async def test_dhcp_discovery_updates_known_host(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """A new lease for a configured matrix just refreshes its host."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=UNIQUE_ID, data={CONF_HOST: "192.168.10.99"}
    )
    entry.add_to_hass(hass)

    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=DHCP_INFO
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST


async def test_reauth_updates_credentials(
    hass: HomeAssistant, patch_clientsession: PatchClientsession
) -> None:
    """Reauth swaps the stored credentials without creating a second entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID,
        data={CONF_HOST: HOST, CONF_USERNAME: "admin", CONF_PASSWORD: "old"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch_clientsession(make_session()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "new"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"
