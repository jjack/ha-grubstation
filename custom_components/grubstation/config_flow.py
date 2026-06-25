"""Adds config flow for Blueprint."""

from __future__ import annotations

import json
import secrets

from aiohttp import web
import voluptuous as vol
from yarl import URL

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.components.network.util import async_get_source_ip
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_MAC, CONF_PIN, CONF_PORT, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import network, selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import GrubStationApiClient, GrubStationApiInvalidPinError, GrubStationApiPinRequiredError
from .const import (
    CONF_APPLY_CONFIG,
    CONF_BOOT_OPTIONS,
    CONF_DAEMONLESS,
    CONF_HA_DAEMON_URL,
    CONF_HA_GRUB_URL,
    CONF_TURN_OFF_ACTION,
    DEFAULT_AGENT_PORT,
    DEFAULT_DAEMONLESS,
    DOMAIN,
    LOGGER,
    SERVER_PORT,
)


async def async_handle_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    request: web.Request,
) -> web.Response | None:
    """Handle webhook callback."""
    return web.json_response({"status": "ok"})


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
        self._webhook_id: str | None = None
        self._api_key: str | None = None
        self._temporary_webhook_registered: bool = False
        self._daemonless_paired: bool = False

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
                if self._is_daemonless:
                    return await self.async_step_daemonless_onboarding()
                return await self.async_step_pairing()

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

    async def async_step_pairing(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle pairing step."""
        _errors = {}
        if user_input is not None:
            if not self._webhook_id:
                self._webhook_id = webhook.async_generate_id()
            if not self._api_key:
                self._api_key = secrets.token_hex(32)

        ha_daemon_url, ha_grub_url = await self._async_generate_urls()

        if user_input is not None:
            self._ha_daemon_url = user_input.get(CONF_HA_DAEMON_URL, ha_daemon_url)
            self._ha_grub_url = user_input.get(CONF_HA_GRUB_URL, ha_grub_url)
            self._apply_config = user_input.get(CONF_APPLY_CONFIG, True)
            self._turn_off_action = user_input.get(CONF_TURN_OFF_ACTION)

            try:
                webhook.async_register(
                    self.hass,
                    DOMAIN,
                    "GrubStation Webhook",
                    self._webhook_id,
                    async_handle_webhook,
                )
                client = GrubStationApiClient(
                    config={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_MAC: self._mac,
                        CONF_DAEMONLESS: self._is_daemonless,
                        CONF_WEBHOOK_ID: self._webhook_id,
                        CONF_API_KEY: self._api_key,
                        CONF_HA_DAEMON_URL: self._ha_daemon_url,
                        CONF_HA_GRUB_URL: self._ha_grub_url,
                        CONF_APPLY_CONFIG: self._apply_config,
                    },
                    session=async_create_clientsession(self.hass),
                )
                response_data = await client.async_pair()
            except GrubStationApiPinRequiredError:
                webhook.async_unregister(self.hass, self._webhook_id)
                return await self.async_step_pin()
            except Exception as exception:  # noqa: BLE001
                LOGGER.exception(exception)
                _errors["base"] = "connection"
                webhook.async_unregister(self.hass, self._webhook_id)
            else:
                webhook.async_unregister(self.hass, self._webhook_id)
                self._mac = response_data.get("mac", self._mac)
                self._boot_options = response_data.get("boot_options")
                return self._async_create_grubstation_entry()

        return self.async_show_form(
            step_id="pairing",
            data_schema=vol.Schema({}),
            errors=_errors,
        )

    async def async_step_pin(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle PIN authentication step."""
        _errors = {}
        if user_input is not None:
            pin = user_input[CONF_PIN]
            try:
                webhook.async_register(
                    self.hass,
                    DOMAIN,
                    "GrubStation Webhook",
                    self._webhook_id,
                    async_handle_webhook,
                )
                client = GrubStationApiClient(
                    config={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_MAC: self._mac,
                        CONF_DAEMONLESS: self._is_daemonless,
                        CONF_WEBHOOK_ID: self._webhook_id,
                        CONF_API_KEY: self._api_key,
                        CONF_HA_DAEMON_URL: self._ha_daemon_url,
                        CONF_HA_GRUB_URL: self._ha_grub_url,
                        CONF_APPLY_CONFIG: self._apply_config,
                    },
                    session=async_create_clientsession(self.hass),
                )
                response_data = await client.async_pair(pin=pin)
            except GrubStationApiInvalidPinError:
                _errors["base"] = "invalid_pin"
                webhook.async_unregister(self.hass, self._webhook_id)
            except Exception as exception:  # noqa: BLE001
                LOGGER.exception(exception)
                _errors["base"] = "connection"
                webhook.async_unregister(self.hass, self._webhook_id)
            else:
                webhook.async_unregister(self.hass, self._webhook_id)
                self._mac = response_data.get("mac", self._mac)
                self._boot_options = response_data.get("boot_options")
                return self._async_create_grubstation_entry()

        return self.async_show_form(
            step_id="pin",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PIN): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        )
                    )
                }
            ),
            errors=_errors,
        )

    async def async_step_daemonless_onboarding(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle daemonless onboarding step."""
        _errors = {}

        if not self._webhook_id:
            self._webhook_id = webhook.async_generate_id()
        if not self._api_key:
            self._api_key = secrets.token_hex(32)

        ha_daemon_url, ha_grub_url = await self._async_generate_urls()

        self._ha_daemon_url = ha_daemon_url
        self._ha_grub_url = ha_grub_url
        self._apply_config = True
        self._turn_off_action = None

        payload_dict = {
            "ha_daemon_url": ha_daemon_url,
            "webhook_id": self._webhook_id,
            "api_key": self._api_key,
            "ha_grub_url": f"{ha_grub_url}/api/grubstation/boot",
            "apply_config": True,
        }
        payload_str = json.dumps(payload_dict)
        pairing_command = f"sudo grubstation pair --payload '{payload_str}'"

        if not self._temporary_webhook_registered:
            webhook.async_register(
                self.hass,
                DOMAIN,
                "GrubStation Temporary Webhook",
                self._webhook_id,
                self._async_handle_daemonless_webhook,
            )
            self._temporary_webhook_registered = True

        if user_input is not None:
            if self._daemonless_paired:
                webhook.async_unregister(self.hass, self._webhook_id)
                self._temporary_webhook_registered = False
                return self._async_create_grubstation_entry()
            _errors["base"] = "waiting_for_device_callback"

        return self.async_show_form(
            step_id="daemonless_onboarding",
            description_placeholders={
                "pairing_command": pairing_command,
            },
            data_schema=vol.Schema({}),
            errors=_errors,
        )

    async def _async_handle_daemonless_webhook(
        self,
        hass: HomeAssistant,
        webhook_id: str,
        request: web.Request,
    ) -> web.Response | None:
        """Handle daemonless callback."""
        try:
            payload = await request.json()
            if payload.get("action") == "update_boot_options":
                self._boot_options = payload.get("boot_options")
                self._daemonless_paired = True
        except Exception:  # noqa: BLE001
            pass
        return web.json_response({"status": "ok"})

    @callback
    def _async_create_grubstation_entry(self) -> config_entries.ConfigFlowResult:
        """Create the config entry."""
        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_MAC: self._mac,
            CONF_WEBHOOK_ID: self._webhook_id,
            CONF_API_KEY: self._api_key,
            CONF_HA_DAEMON_URL: self._ha_daemon_url,
            CONF_HA_GRUB_URL: self._ha_grub_url,
            CONF_APPLY_CONFIG: self._apply_config,
            CONF_TURN_OFF_ACTION: self._turn_off_action,
        }
        if self._is_daemonless:
            title = f"GrubStation ({self._host}) [Manual]"
            data.update(
                {
                    CONF_DAEMONLESS: True,
                    CONF_BOOT_OPTIONS: self._boot_options,
                }
            )
        else:
            title = f"{self._hostname} ({self._host})" if self._hostname else f"GrubStation ({self._host})"
        return self.async_create_entry(title=title, data=data)

    async def _async_generate_urls(self) -> tuple[str, str]:
        """Generate default URLs for HA daemon and GRUB."""
        try:
            ha_daemon_url = network.get_url(self.hass, require_ssl=True, allow_internal=True, allow_external=False)
            ha_grub_url = network.get_url(self.hass, require_ssl=False, allow_internal=True, allow_external=False)
        except network.NoURLAvailableError:
            ha_daemon_url = "http://homeassistant.local:8123"
            ha_grub_url = "http://homeassistant.local:8123"

        # GRUB strictly needs an HTTP IP address and port.
        try:
            ha_ip = await async_get_source_ip(self.hass, self._host)
            url_obj = URL(ha_grub_url).with_scheme("http").with_host(ha_ip)

            # Ensure we have a port. Default to 8123 if it was missing or 443
            if url_obj.port in (None, 80, 443):
                url_obj = url_obj.with_port(SERVER_PORT)

            ha_grub_url = str(url_obj)
        except Exception:  # noqa: BLE001
            LOGGER.debug("Could not determine local IP for ha_grub_url")
            if ha_grub_url.startswith("https"):
                ha_grub_url = ha_grub_url.replace("https", "http", 1)

        return ha_daemon_url, ha_grub_url
