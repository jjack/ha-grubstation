"""Adds config flow for Blueprint."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT
from homeassistant.helpers import selector
from homeassistant.loader import async_get_loaded_integration

from .const import CONF_BOOT_OPTIONS, CONF_DAEMONLESS, DEFAULT_AGENT_PORT, DEFAULT_DAEMONLESS, DOMAIN


class BlueprintFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Blueprint."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None
        self._hostname: str | None = None
        self._port: int = DEFAULT_AGENT_PORT
        self._mac: str | None = None
        self._is_daemonless: bool = False
        self._boot_options: list[str] | None = None

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        _errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input[CONF_PORT]
            self._mac = user_input.get(CONF_MAC)
            self._is_daemonless = user_input.get(CONF_DAEMONLESS, False)

            if self._is_daemonless and not self._mac:
                _errors[CONF_MAC] = "mac_required_for_daemonless"
            else:
                return self.async_create_entry(
                    title=self._host,
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_MAC: self._mac,
                        CONF_DAEMONLESS: self._is_daemonless,
                        CONF_BOOT_OPTIONS: self._boot_options,
                    },
                )

        integration = async_get_loaded_integration(self.hass, DOMAIN)
        assert integration.documentation is not None, "Integration documentation URL is not set in manifest.json"

        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "documentation_url": integration.documentation,
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=(user_input or {}).get(CONF_HOST, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(
                        CONF_PORT,
                        default=(user_input or {}).get(CONF_PORT, DEFAULT_AGENT_PORT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1025,
                            max=65535,
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                    vol.Optional(
                        CONF_MAC,
                        default=(user_input or {}).get(CONF_MAC, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(
                        CONF_DAEMONLESS,
                        default=(user_input or {}).get(CONF_DAEMONLESS, DEFAULT_DAEMONLESS),
                    ): selector.BooleanSelector(),
                },
            ),
            errors=_errors,
        )
