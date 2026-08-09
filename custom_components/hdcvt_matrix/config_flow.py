"""Config flow for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
import voluptuous as vol

from .api import (
    HdcvtMatrixClient,
    MatrixAuthError,
    MatrixConnectionError,
    MatrixError,
    MatrixInfo,
)
from .const import (
    CONF_FEATURES,
    CONF_USE_DEFAULT_CREDENTIALS,
    DEFAULT_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
    ERROR_UNSUPPORTED_DEVICE,
    FEATURES,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
        ),
        vol.Optional(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)

# Setup steps offer the factory credentials as a one-click default. Reauth
# deliberately does not: you are there because the stored credentials stopped
# working, so the factory pair is the least likely answer.
CREDENTIALS_SCHEMA = vol.Schema(
    {vol.Optional(CONF_USE_DEFAULT_CREDENTIALS, default=True): BooleanSelector()}
).extend(REAUTH_SCHEMA.schema)


def _resolve_credentials(user_input: dict[str, Any]) -> dict[str, Any]:
    """Turn the form values into the credentials to store on the entry.

    The checkbox wins over the text fields when ticked, so that a half-filled
    form cannot quietly send something other than what the label promises. The
    flag itself is a UI affordance and is not persisted.
    """
    if user_input.get(CONF_USE_DEFAULT_CREDENTIALS):
        return {CONF_USERNAME: DEFAULT_USERNAME, CONF_PASSWORD: DEFAULT_PASSWORD}

    credentials = {}
    if username := user_input.get(CONF_USERNAME):
        credentials[CONF_USERNAME] = username
    if password := user_input.get(CONF_PASSWORD):
        credentials[CONF_PASSWORD] = password
    return credentials


USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="url")
        ),
    }
).extend(CREDENTIALS_SCHEMA.schema)


OPTIONS_SCHEMA = vol.Schema(
    {
        # Nothing outside core routing is created until it is picked here, so
        # a default install stays at ten entities rather than ninety.
        vol.Optional(CONF_FEATURES, default=[]): SelectSelector(
            SelectSelectorConfig(
                options=FEATURES,
                multiple=True,
                mode=SelectSelectorMode.LIST,
                translation_key="features",
            )
        ),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                max=MAX_SCAN_INTERVAL,
                step=1,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)


class HdcvtMatrixOptionsFlow(OptionsFlowWithReload):
    """Let the polling interval be tuned after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_FEATURES: user_input.get(CONF_FEATURES, []),
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )


class HdcvtMatrixConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for a matrix."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HdcvtMatrixOptionsFlow:
        """Return the options flow."""
        return HdcvtMatrixOptionsFlow()

    def __init__(self) -> None:
        """Initialise the flow."""
        self._host: str | None = None
        self._discovered_name: str | None = None

    async def _async_validate(
        self, host: str, username: str | None, password: str | None
    ) -> tuple[MatrixInfo | None, str | None]:
        """Check we can reach the matrix and that the credentials are accepted."""
        client = HdcvtMatrixClient(
            host,
            async_get_clientsession(self.hass),
            username=username,
            password=password,
        )
        try:
            await client.async_login()
            return await client.async_get_info(), None
        except MatrixAuthError:
            return None, ERROR_INVALID_AUTH
        except MatrixConnectionError:
            return None, ERROR_CANNOT_CONNECT
        except MatrixError as err:
            _LOGGER.debug("Unexpected reply from %s: %s", host, err)
            return None, ERROR_UNSUPPORTED_DEVICE

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow started by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            credentials = _resolve_credentials(user_input)
            info, error = await self._async_validate(
                host,
                credentials.get(CONF_USERNAME),
                credentials.get(CONF_PASSWORD),
            )
            if info is not None:
                await self.async_set_unique_id(format_mac(info.mac_address))
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=info.model,
                    data={CONF_HOST: host, **credentials},
                )
            errors["base"] = error or ERROR_UNKNOWN

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point an existing entry at a new address, or new credentials."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            credentials = _resolve_credentials(user_input)
            info, error = await self._async_validate(
                host,
                credentials.get(CONF_USERNAME),
                credentials.get(CONF_PASSWORD),
            )
            if info is not None:
                # Guard against being pointed at a different matrix: the entry
                # already owns a MAC, and silently rebinding it would orphan
                # every entity attached to the old one.
                await self.async_set_unique_id(format_mac(info.mac_address))
                self._abort_if_unique_id_mismatch(reason="wrong_matrix")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host, **credentials}
                )
            errors["base"] = error or ERROR_UNKNOWN

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA,
                user_input or {CONF_HOST: entry.data[CONF_HOST]},
            ),
            errors=errors,
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a matrix found on the network by its DHCP lease."""
        await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})

        self._host = discovery_info.ip
        self._discovered_name = discovery_info.hostname

        # Confirm it really is a matrix before bothering the user with a form.
        info, error = await self._async_validate(discovery_info.ip, None, None)
        if error == ERROR_CANNOT_CONNECT:
            return self.async_abort(reason=ERROR_CANNOT_CONNECT)
        if info is None:
            return self.async_abort(reason=ERROR_UNSUPPORTED_DEVICE)

        self._discovered_name = info.model
        self.context["title_placeholders"] = {"name": info.model}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials for a discovered matrix."""
        if self._host is None:
            # Only reachable via async_step_dhcp, which always sets the host.
            # A real check rather than an assert, which -O would strip.
            return self.async_abort(reason=ERROR_UNKNOWN)
        errors: dict[str, str] = {}

        if user_input is not None:
            credentials = _resolve_credentials(user_input)
            info, error = await self._async_validate(
                self._host,
                credentials.get(CONF_USERNAME),
                credentials.get(CONF_PASSWORD),
            )
            if info is not None:
                return self.async_create_entry(
                    title=info.model,
                    data={CONF_HOST: self._host, **credentials},
                )
            errors["base"] = error or ERROR_UNKNOWN

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
            description_placeholders={
                "name": self._discovered_name or "HDMI Matrix",
                "host": self._host,
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle credentials the matrix no longer accepts."""
        self._host = entry_data[CONF_HOST]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect replacement credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            info, error = await self._async_validate(
                entry.data[CONF_HOST],
                user_input.get(CONF_USERNAME),
                user_input.get(CONF_PASSWORD),
            )
            if info is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
            errors["base"] = error or ERROR_UNKNOWN

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                REAUTH_SCHEMA,
                {CONF_USERNAME: entry.data.get(CONF_USERNAME)},
            ),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )
