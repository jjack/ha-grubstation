"""Adds config flow for GrubStation."""

from __future__ import annotations

import contextlib
import json
import secrets
from typing import Any

from aiohttp import web
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.components.network.util import async_get_source_ip
from homeassistant.const import CONF_API_KEY, CONF_IP_ADDRESS, CONF_MAC, CONF_PIN, CONF_PORT, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import network, selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.loader import async_get_loaded_integration

from .api import (
    GrubStationApiClient,
    GrubStationApiClientError,
    GrubStationApiConflictError,
    GrubStationApiInvalidPinError,
    GrubStationApiPinRequiredError,
)
from .const import (
    API_KEY_LENGTH,
    CONF_ADVANCED_OPTIONS,
    CONF_BOOT_OPTIONS,
    CONF_DAEMON_TOKEN,
    CONF_DAEMONLESS,
    CONF_HA_DAEMON_URL,
    CONF_HA_GRUB_URL,
    CONF_HOSTNAME,
    CONF_TURN_OFF_ACTION,
    CONF_UPDATE_GRUB,
    CONF_WOL_BROADCAST,
    CONF_WOL_PORT,
    DEFAULT_AGENT_PORT,
    DEFAULT_SERVER_PORT,
    DEFAULT_WOL_BROADCAST,
    DEFAULT_WOL_PORT,
    DOMAIN,
    LOGGER,
)
from .helpers import format_display_name, is_ip_address, normalize_mac

CONF_SETUP_TYPE = "setup_type"
SETUP_TYPE_AGENT = "agent"
SETUP_TYPE_DAEMONLESS = "daemonless"


async def async_handle_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    request: web.Request,
) -> web.Response | None:
    """Handle webhook callback."""
    return web.json_response({"status": "ok"})


class GrubStationFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for GrubStation."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return GrubStationOptionsFlowHandler(config_entry)

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._ip_address: str | None = None
        self._hostname: str | None = None
        self._port: int = DEFAULT_AGENT_PORT
        self._mac: str | None = None
        self._is_daemonless: bool = False
        self._boot_options: list[str] | None = None
        self._webhook_id: str | None = None
        self._api_key: str | None = None
        self._temporary_webhook_registered: bool = False
        self._daemonless_paired: bool = False
        self._paired: str | None = None
        self._daemon_token: str | None = None
        self._wol_broadcast: str = DEFAULT_WOL_BROADCAST
        self._wol_port: int = DEFAULT_WOL_PORT
        self._turn_off_action: str | None = None

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> config_entries.ConfigFlowResult:
        """Handle zeroconf discovery."""
        LOGGER.debug("Zeroconf discovery payload: %s", discovery_info)
        properties = discovery_info.properties

        def _get_prop(key: str) -> str | None:
            val = properties.get(key)
            if isinstance(val, bytes):
                return val.decode("utf-8")
            return val

        paired_str = _get_prop("paired")

        self._ip_address = str(discovery_info.ip_address)
        self._port = discovery_info.port or DEFAULT_AGENT_PORT

        # Check if already configured by IP address
        for entry in self._async_current_entries():
            if entry.data.get(CONF_IP_ADDRESS) == self._ip_address:
                return self.async_abort(reason="already_configured")

        if discovery_info.hostname:
            self._hostname = discovery_info.hostname.removesuffix(".")
        self._paired = paired_str
        self._is_daemonless = False

        self.context["title_placeholders"] = {"name": format_display_name(self._ip_address, self._hostname)}

        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm zeroconf discovery and enter PIN."""
        _errors = {}
        ha_daemon_url, ha_grub_url = await self._async_generate_urls()

        if user_input is not None:
            pin = user_input[CONF_PIN]
            self._update_grub = user_input.get(CONF_UPDATE_GRUB, True)
            advanced = user_input.get(CONF_ADVANCED_OPTIONS, {})
            self._ha_daemon_url = advanced.get(CONF_HA_DAEMON_URL, ha_daemon_url)
            self._ha_grub_url = advanced.get(CONF_HA_GRUB_URL, ha_grub_url)
            self._wol_broadcast = advanced.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST)
            self._wol_port = int(advanced.get(CONF_WOL_PORT, DEFAULT_WOL_PORT))

            if not self._webhook_id:
                self._webhook_id = webhook.async_generate_id()
            if not self._api_key:
                self._api_key = secrets.token_hex(API_KEY_LENGTH)

            try:
                webhook.async_register(
                    self.hass,
                    DOMAIN,
                    "GrubStation Webhook",
                    self._webhook_id,
                    async_handle_webhook,
                )
                client = GrubStationApiClient(
                    ip_address=self._ip_address,
                    port=self._port,
                    session=async_create_clientsession(self.hass),
                )
                response_data = await client.async_pair(
                    pin=pin,
                    webhook_id=self._webhook_id,
                    api_key=self._api_key,
                    ha_daemon_url=self._ha_daemon_url,
                    ha_grub_url=self._ha_grub_url,
                    update_grub=self._update_grub,
                )
            except GrubStationApiConflictError:
                _errors["base"] = "already_paired"
                webhook.async_unregister(self.hass, self._webhook_id)
            except GrubStationApiPinRequiredError, GrubStationApiInvalidPinError:
                _errors["base"] = "invalid_pin"
                webhook.async_unregister(self.hass, self._webhook_id)
            except Exception as exception:  # noqa: BLE001
                LOGGER.exception(exception)
                _errors["base"] = "connection"
                webhook.async_unregister(self.hass, self._webhook_id)
            else:
                webhook.async_unregister(self.hass, self._webhook_id)
                self._mac = response_data.get("mac", self._mac)
                self._daemon_token = response_data.get("token")
                self._boot_options = response_data.get("boot_options")

                if self._mac:
                    normalized_mac = normalize_mac(self._mac)
                    await self.async_set_unique_id(normalized_mac)
                    self._abort_if_unique_id_configured(updates={CONF_IP_ADDRESS: self._ip_address})
                    self._mac = normalized_mac
                else:
                    await self.async_set_unique_id(self._ip_address)
                    self._abort_if_unique_id_configured()

                return self._async_create_grubstation_entry()

        integration = async_get_loaded_integration(self.hass, DOMAIN)
        assert integration.documentation is not None, "Integration documentation URL is not set in manifest.json"

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PIN): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        )
                    ),
                    vol.Required(CONF_UPDATE_GRUB, default=True): selector.BooleanSelector(),
                    vol.Required(CONF_ADVANCED_OPTIONS): section(
                        vol.Schema(
                            {
                                vol.Required(CONF_HA_DAEMON_URL, default=ha_daemon_url): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Required(CONF_HA_GRUB_URL, default=ha_grub_url): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Optional(CONF_WOL_BROADCAST, default=DEFAULT_WOL_BROADCAST): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Optional(CONF_WOL_PORT, default=DEFAULT_WOL_PORT): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=1,
                                        max=65535,
                                        mode=selector.NumberSelectorMode.BOX,
                                    ),
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                }
            ),
            description_placeholders={
                "documentation_url": integration.documentation,
                "name": self._hostname or self._ip_address,
                "host": self._ip_address,
                "port": self._port,
            },
            errors=_errors,
        )

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            if user_input[CONF_SETUP_TYPE] == SETUP_TYPE_DAEMONLESS:
                self._is_daemonless = True
                return await self.async_step_daemonless_config()
            self._is_daemonless = False
            return await self.async_step_agent_config()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SETUP_TYPE,
                        default=SETUP_TYPE_AGENT,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                SETUP_TYPE_AGENT,
                                SETUP_TYPE_DAEMONLESS,
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                            translation_key="setup_type_options",
                        )
                    )
                }
            ),
        )

    async def async_step_agent_config(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Configure a standard agent host."""
        _errors: dict[str, str] = {}
        ha_daemon_url, ha_grub_url = await self._async_generate_urls()

        if user_input is not None:
            self._ip_address = user_input[CONF_IP_ADDRESS]

            self._update_grub = user_input.get(CONF_UPDATE_GRUB, True)
            advanced = user_input.get(CONF_ADVANCED_OPTIONS, {})
            self._port = int(advanced.get(CONF_PORT, DEFAULT_AGENT_PORT))
            self._ha_daemon_url = advanced.get(CONF_HA_DAEMON_URL, ha_daemon_url)
            self._ha_grub_url = getattr(self, "_ha_grub_url", None) or advanced.get(CONF_HA_GRUB_URL, ha_grub_url)
            self._wol_broadcast = advanced.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST)
            self._wol_port = int(advanced.get(CONF_WOL_PORT, DEFAULT_WOL_PORT))
            self._is_daemonless = False

            if not is_ip_address(self._ip_address):
                _errors[CONF_IP_ADDRESS] = "invalid_ip"
            else:
                pin = user_input[CONF_PIN]
                if not self._webhook_id:
                    self._webhook_id = webhook.async_generate_id()
                if not self._api_key:
                    self._api_key = secrets.token_hex(API_KEY_LENGTH)

                try:
                    webhook.async_register(
                        self.hass,
                        DOMAIN,
                        "GrubStation Webhook",
                        self._webhook_id,
                        async_handle_webhook,
                    )
                    client = GrubStationApiClient(
                        ip_address=self._ip_address,
                        port=self._port,
                        session=async_create_clientsession(self.hass),
                    )
                    response_data = await client.async_pair(
                        pin=pin,
                        webhook_id=self._webhook_id,
                        api_key=self._api_key,
                        ha_daemon_url=self._ha_daemon_url,
                        ha_grub_url=self._ha_grub_url,
                        update_grub=self._update_grub,
                    )
                except GrubStationApiConflictError:
                    _errors["base"] = "already_paired"
                    webhook.async_unregister(self.hass, self._webhook_id)
                except GrubStationApiPinRequiredError, GrubStationApiInvalidPinError:
                    _errors["base"] = "invalid_pin"
                    webhook.async_unregister(self.hass, self._webhook_id)
                except Exception as exception:  # noqa: BLE001
                    LOGGER.exception(exception)
                    _errors["base"] = "connection"
                    webhook.async_unregister(self.hass, self._webhook_id)
                else:
                    webhook.async_unregister(self.hass, self._webhook_id)
                    self._mac = response_data.get("mac")
                    self._daemon_token = response_data.get("token")
                    self._boot_options = response_data.get("boot_options")

                    if self._mac:
                        normalized_mac = normalize_mac(self._mac)
                        await self.async_set_unique_id(normalized_mac)
                        self._abort_if_unique_id_configured(updates={CONF_IP_ADDRESS: self._ip_address})
                        self._mac = normalized_mac
                    else:
                        await self.async_set_unique_id(self._ip_address)
                        self._abort_if_unique_id_configured()

                    return self._async_create_grubstation_entry()

        # Defaults for the advanced options
        current_advanced = (user_input or {}).get(CONF_ADVANCED_OPTIONS, {})
        default_port = current_advanced.get(CONF_PORT, DEFAULT_AGENT_PORT)
        default_ha_daemon = current_advanced.get(CONF_HA_DAEMON_URL, ha_daemon_url)
        default_ha_grub = current_advanced.get(CONF_HA_GRUB_URL, ha_grub_url)
        default_update_grub = (user_input or {}).get(CONF_UPDATE_GRUB, True)
        default_wol_broadcast = current_advanced.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST)
        default_wol_port = current_advanced.get(CONF_WOL_PORT, DEFAULT_WOL_PORT)

        integration = async_get_loaded_integration(self.hass, DOMAIN)
        assert integration.documentation is not None, "Integration documentation URL is not set in manifest.json"

        return self.async_show_form(
            step_id="agent_config",
            description_placeholders={
                "documentation_url": integration.documentation,
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IP_ADDRESS,
                        default=(user_input or {}).get(CONF_IP_ADDRESS, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(
                        CONF_PIN,
                        default=(user_input or {}).get(CONF_PIN, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        )
                    ),
                    vol.Required(
                        CONF_UPDATE_GRUB,
                        default=default_update_grub,
                    ): selector.BooleanSelector(),
                    vol.Required(CONF_ADVANCED_OPTIONS): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_PORT,
                                    default=default_port,
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=1025,
                                        max=65535,
                                        mode=selector.NumberSelectorMode.BOX,
                                    ),
                                ),
                                vol.Required(
                                    CONF_HA_DAEMON_URL,
                                    default=default_ha_daemon,
                                ): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Required(
                                    CONF_HA_GRUB_URL,
                                    default=default_ha_grub,
                                ): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Optional(
                                    CONF_WOL_BROADCAST,
                                    default=default_wol_broadcast,
                                ): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Optional(
                                    CONF_WOL_PORT,
                                    default=default_wol_port,
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=1,
                                        max=65535,
                                        mode=selector.NumberSelectorMode.BOX,
                                    ),
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                },
            ),
            errors=_errors,
        )

    async def async_step_daemonless_config(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Configure a daemonless host."""
        _errors: dict[str, str] = {}
        ha_daemon_url, ha_grub_url = await self._async_generate_urls()

        if user_input is not None:
            self._ip_address = user_input[CONF_IP_ADDRESS]
            self._mac = user_input.get(CONF_MAC)
            self._update_grub = user_input.get(CONF_UPDATE_GRUB, True)
            self._turn_off_action = user_input.get(CONF_TURN_OFF_ACTION)

            advanced = user_input.get(CONF_ADVANCED_OPTIONS, {})
            self._ha_daemon_url = advanced.get(CONF_HA_DAEMON_URL, ha_daemon_url)
            self._ha_grub_url = advanced.get(CONF_HA_GRUB_URL, ha_grub_url)
            self._wol_broadcast = advanced.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST)
            self._wol_port = int(advanced.get(CONF_WOL_PORT, DEFAULT_WOL_PORT))
            self._port = DEFAULT_AGENT_PORT
            self._is_daemonless = True

            if not is_ip_address(self._ip_address):
                _errors[CONF_IP_ADDRESS] = "invalid_ip"
            elif not self._mac:
                _errors[CONF_MAC] = "mac_required_for_daemonless"
            else:
                normalized_mac = normalize_mac(self._mac)
                await self.async_set_unique_id(normalized_mac)
                self._abort_if_unique_id_configured(updates={CONF_IP_ADDRESS: self._ip_address})
                self._mac = normalized_mac

                return await self.async_step_daemonless_onboarding()

        # Defaults for the advanced options
        current_advanced = (user_input or {}).get(CONF_ADVANCED_OPTIONS, {})
        default_ha_daemon = current_advanced.get(CONF_HA_DAEMON_URL, ha_daemon_url)
        default_ha_grub = current_advanced.get(CONF_HA_GRUB_URL, ha_grub_url)
        default_update_grub = (user_input or {}).get(CONF_UPDATE_GRUB, True)
        default_wol_broadcast = current_advanced.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST)
        default_wol_port = current_advanced.get(CONF_WOL_PORT, DEFAULT_WOL_PORT)

        integration = async_get_loaded_integration(self.hass, DOMAIN)
        assert integration.documentation is not None, "Integration documentation URL is not set in manifest.json"

        return self.async_show_form(
            step_id="daemonless_config",
            description_placeholders={
                "documentation_url": integration.documentation,
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IP_ADDRESS,
                        default=(user_input or {}).get(CONF_IP_ADDRESS, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(
                        CONF_MAC,
                        default=(user_input or {}).get(CONF_MAC, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(
                        CONF_UPDATE_GRUB,
                        default=default_update_grub,
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_TURN_OFF_ACTION,
                        default=(user_input or {}).get(CONF_TURN_OFF_ACTION, vol.UNDEFINED),
                    ): selector.ActionSelector(),
                    vol.Required(CONF_ADVANCED_OPTIONS): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_HA_DAEMON_URL,
                                    default=default_ha_daemon,
                                ): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Required(
                                    CONF_HA_GRUB_URL,
                                    default=default_ha_grub,
                                ): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Optional(
                                    CONF_WOL_BROADCAST,
                                    default=default_wol_broadcast,
                                ): selector.TextSelector(
                                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                                ),
                                vol.Optional(
                                    CONF_WOL_PORT,
                                    default=default_wol_port,
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=1,
                                        max=65535,
                                        mode=selector.NumberSelectorMode.BOX,
                                    ),
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                },
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
            self._api_key = secrets.token_hex(API_KEY_LENGTH)

        if not getattr(self, "_ha_daemon_url", None) or not getattr(self, "_ha_grub_url", None):
            ha_daemon_url, ha_grub_url = await self._async_generate_urls()
            if not getattr(self, "_ha_daemon_url", None):
                self._ha_daemon_url = ha_daemon_url
            if not getattr(self, "_ha_grub_url", None):
                self._ha_grub_url = ha_grub_url

        self._update_grub = getattr(self, "_update_grub", True)

        payload_dict = {
            "ha_daemon_url": self._ha_daemon_url,
            "webhook_id": self._webhook_id,
            "api_key": self._api_key,
            "ha_grub_url": f"{self._ha_grub_url}/api/grubstation/boot",
            "update_grub": self._update_grub,
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
            LOGGER.debug("Received daemonless webhook callback payload: %s", payload)
            if payload.get("action") == "update_boot_options" or "boot_options" in payload:
                self._boot_options = payload.get("boot_options")
                self._daemonless_paired = True
                LOGGER.info("GrubStation daemonless host successfully paired via webhook!")
            else:
                LOGGER.warning("Received daemonless webhook with unexpected action: %s", payload.get("action"))
        except Exception as exception:  # noqa: BLE001
            LOGGER.exception("Error handling daemonless webhook callback: %s", exception)
        return web.json_response({"status": "ok"})

    @callback
    def _async_create_grubstation_entry(self) -> config_entries.ConfigFlowResult:
        """Create the config entry."""
        data = {
            CONF_IP_ADDRESS: self._ip_address,
            CONF_PORT: self._port,
            CONF_MAC: self._mac,
            CONF_WEBHOOK_ID: self._webhook_id,
            CONF_API_KEY: self._api_key,
            CONF_HA_DAEMON_URL: self._ha_daemon_url,
            CONF_HA_GRUB_URL: self._ha_grub_url,
            CONF_UPDATE_GRUB: self._update_grub,
            CONF_TURN_OFF_ACTION: self._turn_off_action,
            CONF_HOSTNAME: self._hostname,
            CONF_DAEMON_TOKEN: self._daemon_token,
            CONF_WOL_BROADCAST: self._wol_broadcast,
            CONF_WOL_PORT: self._wol_port,
        }
        if self._is_daemonless:
            title = f"GrubStation ({self._ip_address}) [Manual]"
            data.update(
                {
                    CONF_DAEMONLESS: True,
                    CONF_BOOT_OPTIONS: self._boot_options,
                }
            )
        else:
            title = format_display_name(self._ip_address, self._hostname, "GrubStation")
        return self.async_create_entry(title=title, data=data)

    async def _async_generate_urls(self) -> tuple[str, str]:
        """Generate default URLs and options for HA daemon and GRUB."""
        # 1. Fetch available configured URLs (exactly once per type)
        secure_url = None
        with contextlib.suppress(network.NoURLAvailableError):
            secure_url = network.get_url(self.hass, require_ssl=True, allow_internal=True, allow_external=False)

        insecure_url = None
        with contextlib.suppress(network.NoURLAvailableError):
            insecure_url = network.get_url(self.hass, require_ssl=False, allow_internal=True, allow_external=False)

        # GrubStation prefers to use HTTPs to talk to Home Assistant (if available) but GRUB requires
        # HTTP for the boot portion
        ha_daemon_url = secure_url or insecure_url
        grub_url = insecure_url

        # 2. Apply fallback cascade logic if either default URL is missing
        if not ha_daemon_url or not grub_url:
            ha_ip = None
            with contextlib.suppress(Exception):
                ha_ip = await async_get_source_ip(self.hass, target_ip=None)

            if not ha_ip:
                api = getattr(self.hass.config, "api", None)
                if api and getattr(api, "host", None) not in ("0.0.0.0", "::", None):
                    ha_ip = api.host

            if not ha_ip:
                ha_ip = "127.0.0.1"
                LOGGER.warning(
                    "Could not auto-detect Home Assistant IP address. "
                    "Defaulting to %s — you may need to edit "
                    "the daemon/grub URLs in the integration options if connection fails.",
                    ha_ip,
                )

            port = DEFAULT_SERVER_PORT
            api = getattr(self.hass.config, "api", None)
            if api and getattr(api, "port", None):
                port = api.port

            if not ha_daemon_url:
                ha_daemon_url = f"http://{ha_ip}:{port}"
            if not grub_url:
                grub_url = f"http://{ha_ip}:{port}"

        return ha_daemon_url, grub_url

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Handle initiation of re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Prompt the user to re-enter their pairing PIN and re-pair the device."""
        reauth_entry = self._get_reauth_entry()
        _errors: dict[str, str] = {}

        if user_input is not None:
            pin = user_input[CONF_PIN]
            temp_webhook_id = webhook.async_generate_id()

            try:
                webhook.async_register(
                    self.hass,
                    DOMAIN,
                    "GrubStation Webhook (Reauth)",
                    temp_webhook_id,
                    async_handle_webhook,
                )
                client = GrubStationApiClient(
                    ip_address=reauth_entry.data[CONF_IP_ADDRESS],
                    port=reauth_entry.data[CONF_PORT],
                    session=async_create_clientsession(self.hass),
                )
                response_data = await client.async_pair(
                    pin=pin,
                    webhook_id=reauth_entry.data[CONF_WEBHOOK_ID],
                    api_key=reauth_entry.data[CONF_API_KEY],
                    ha_daemon_url=reauth_entry.data[CONF_HA_DAEMON_URL],
                    ha_grub_url=reauth_entry.data[CONF_HA_GRUB_URL],
                    update_grub=reauth_entry.data.get(CONF_UPDATE_GRUB, True),
                )
            except GrubStationApiInvalidPinError, GrubStationApiPinRequiredError:
                _errors["base"] = "invalid_pin"
                webhook.async_unregister(self.hass, temp_webhook_id)
            except Exception as exception:  # noqa: BLE001
                LOGGER.exception(exception)
                _errors["base"] = "connection"
                webhook.async_unregister(self.hass, temp_webhook_id)
            else:
                webhook.async_unregister(self.hass, temp_webhook_id)
                new_token = response_data.get("token")
                self.hass.config_entries.async_update_entry(
                    reauth_entry,
                    data={**reauth_entry.data, CONF_DAEMON_TOKEN: new_token},
                )
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={
                "hostname": reauth_entry.data.get(CONF_HOSTNAME) or reauth_entry.data.get(CONF_IP_ADDRESS, ""),
            },
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PIN): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        )
                    ),
                }
            ),
            errors=_errors,
        )


class GrubStationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle GrubStation options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        _errors: dict[str, str] = {}

        if user_input is not None:
            # Merge changes into the config entry data
            new_data = dict(self._config_entry.data)
            new_data[CONF_HA_DAEMON_URL] = user_input[CONF_HA_DAEMON_URL]
            new_data[CONF_HA_GRUB_URL] = user_input[CONF_HA_GRUB_URL]
            new_data[CONF_UPDATE_GRUB] = user_input[CONF_UPDATE_GRUB]
            new_data[CONF_TURN_OFF_ACTION] = user_input.get(CONF_TURN_OFF_ACTION)
            new_data[CONF_WOL_BROADCAST] = user_input.get(CONF_WOL_BROADCAST) or DEFAULT_WOL_BROADCAST
            new_data[CONF_WOL_PORT] = int(user_input.get(CONF_WOL_PORT) or DEFAULT_WOL_PORT)

            if new_data.get(CONF_DAEMONLESS) and not new_data.get(CONF_TURN_OFF_ACTION):
                _errors["base"] = "turn_off_action_required_for_daemonless"

            if not _errors:
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=new_data,
                )

                # Best-effort: push updated settings to the daemon.
                # Failures are logged but do not block saving the options.
                if not new_data.get(CONF_DAEMONLESS):
                    try:
                        client = GrubStationApiClient(
                            ip_address=new_data[CONF_IP_ADDRESS],
                            port=new_data[CONF_PORT],
                            session=async_create_clientsession(self.hass),
                        )
                        await client.async_update_config(
                            new_data.get(CONF_DAEMON_TOKEN, ""),
                            ha_daemon_url=new_data[CONF_HA_DAEMON_URL],
                            ha_grub_url=new_data[CONF_HA_GRUB_URL],
                            update_grub=new_data[CONF_UPDATE_GRUB],
                        )
                    except GrubStationApiClientError as err:
                        LOGGER.warning("Could not sync updated config to daemon: %s", err)

                return self.async_create_entry(title="", data={})

        current = self._config_entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HA_DAEMON_URL,
                        default=current.get(CONF_HA_DAEMON_URL, ""),
                    ): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)),
                    vol.Required(
                        CONF_HA_GRUB_URL,
                        default=current.get(CONF_HA_GRUB_URL, ""),
                    ): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)),
                    vol.Required(
                        CONF_UPDATE_GRUB,
                        default=current.get(CONF_UPDATE_GRUB, True),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_TURN_OFF_ACTION,
                        description={"suggested_value": current.get(CONF_TURN_OFF_ACTION)},
                    ): selector.ActionSelector(),
                    vol.Optional(
                        CONF_WOL_BROADCAST,
                        default=current.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST),
                    ): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)),
                    vol.Optional(
                        CONF_WOL_PORT,
                        default=current.get(CONF_WOL_PORT, DEFAULT_WOL_PORT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=65535,
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                }
            ),
            errors=_errors,
        )
