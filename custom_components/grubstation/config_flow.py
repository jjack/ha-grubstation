"""Adds config flow for Blueprint."""

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
from homeassistant.helpers import network, selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.loader import async_get_loaded_integration

from .api import (
    GrubStationApiClient,
    GrubStationApiConflictError,
    GrubStationApiInvalidPinError,
    GrubStationApiPinRequiredError,
)
from .const import (
    CONF_BOOT_OPTIONS,
    CONF_DAEMONLESS,
    CONF_HA_DAEMON_URL,
    CONF_HA_GRUB_URL,
    CONF_TURN_OFF_ACTION,
    CONF_UPDATE_GRUB,
    DEFAULT_AGENT_PORT,
    DEFAULT_DAEMONLESS,
    DOMAIN,
    LOGGER,
    SERVER_PORT,
)
from .helpers import format_display_name, is_ip_address


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

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> config_entries.ConfigFlowResult:
        """Handle zeroconf discovery."""
        LOGGER.debug("Zeroconf discovery payload: %s", discovery_info)
        properties = discovery_info.properties

        def _get_prop(key: str) -> str | None:
            val = properties.get(key)
            if isinstance(val, bytes):
                return val.decode("utf-8")
            return val

        mac = _get_prop("mac")
        paired_str = _get_prop("paired")

        self._ip_address = str(discovery_info.ip_address)
        self._port = discovery_info.port or DEFAULT_AGENT_PORT

        if mac:
            normalized_mac = mac.lower()
            await self.async_set_unique_id(normalized_mac)
            self._abort_if_unique_id_configured(updates={CONF_IP_ADDRESS: self._ip_address})
            self._mac = normalized_mac
        else:
            await self.async_set_unique_id(self._ip_address)
            self._abort_if_unique_id_configured()

        if discovery_info.hostname:
            self._hostname = discovery_info.hostname.removesuffix(".")
        self._paired = paired_str
        self._is_daemonless = False

        self.context["title_placeholders"] = {
            "name": f"{self._ip_address} ({self._hostname})" if self._hostname else self._ip_address
        }

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
            self._ha_daemon_url = user_input.get(CONF_HA_DAEMON_URL, ha_daemon_url)
            self._ha_grub_url = user_input.get(CONF_HA_GRUB_URL, ha_grub_url)
            self._turn_off_action = user_input.get(CONF_TURN_OFF_ACTION)

            if not self._webhook_id:
                self._webhook_id = webhook.async_generate_id()
            if not self._api_key:
                self._api_key = secrets.token_hex(32)

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
                        CONF_IP_ADDRESS: self._ip_address,
                        CONF_PORT: self._port,
                        CONF_MAC: self._mac,
                        CONF_DAEMONLESS: self._is_daemonless,
                        CONF_WEBHOOK_ID: self._webhook_id,
                        CONF_API_KEY: self._api_key,
                        CONF_HA_DAEMON_URL: self._ha_daemon_url,
                        CONF_HA_GRUB_URL: self._ha_grub_url,
                        CONF_UPDATE_GRUB: self._update_grub,
                    },
                    session=async_create_clientsession(self.hass),
                )
                response_data = await client.async_pair(pin=pin)
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
                self._boot_options = response_data.get("boot_options")
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
                    vol.Required(CONF_HA_DAEMON_URL, default=ha_daemon_url): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_HA_GRUB_URL, default=ha_grub_url): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_UPDATE_GRUB, default=True): selector.BooleanSelector(),
                    vol.Optional(CONF_TURN_OFF_ACTION): selector.ActionSelector(),
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
        _errors: dict[str, str] = {}
        if user_input is not None:
            self._ip_address = user_input[CONF_IP_ADDRESS]
            self._port = user_input[CONF_PORT]
            self._mac = user_input.get(CONF_MAC)
            self._is_daemonless = user_input.get(CONF_DAEMONLESS, False)
            self._turn_off_action = user_input.get(CONF_TURN_OFF_ACTION)

            if not is_ip_address(self._ip_address):
                _errors[CONF_IP_ADDRESS] = "invalid_ip"
            elif self._is_daemonless and not self._mac:
                _errors[CONF_MAC] = "mac_required_for_daemonless"
            elif self._is_daemonless and not self._turn_off_action:
                _errors[CONF_TURN_OFF_ACTION] = "turn_off_action_required_for_daemonless"
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
                        CONF_IP_ADDRESS,
                        default=(user_input or {}).get(CONF_IP_ADDRESS, vol.UNDEFINED),
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
                    vol.Optional(
                        CONF_TURN_OFF_ACTION,
                        default=(user_input or {}).get(CONF_TURN_OFF_ACTION, vol.UNDEFINED),
                    ): selector.ActionSelector(),
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
            self._update_grub = user_input.get(CONF_UPDATE_GRUB, True)
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
                        CONF_IP_ADDRESS: self._ip_address,
                        CONF_PORT: self._port,
                        CONF_MAC: self._mac,
                        CONF_DAEMONLESS: self._is_daemonless,
                        CONF_WEBHOOK_ID: self._webhook_id,
                        CONF_API_KEY: self._api_key,
                        CONF_HA_DAEMON_URL: self._ha_daemon_url,
                        CONF_HA_GRUB_URL: self._ha_grub_url,
                        CONF_UPDATE_GRUB: self._update_grub,
                    },
                    session=async_create_clientsession(self.hass),
                )
                response_data = await client.async_pair()
            except GrubStationApiPinRequiredError:
                webhook.async_unregister(self.hass, self._webhook_id)
                return await self.async_step_pin()
            except GrubStationApiConflictError:
                _errors["base"] = "already_paired"
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
            step_id="pairing",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HA_DAEMON_URL, default=ha_daemon_url): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_HA_GRUB_URL, default=ha_grub_url): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_TURN_OFF_ACTION): selector.ActionSelector(),
                }
            ),
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
                        CONF_IP_ADDRESS: self._ip_address,
                        CONF_PORT: self._port,
                        CONF_MAC: self._mac,
                        CONF_DAEMONLESS: self._is_daemonless,
                        CONF_WEBHOOK_ID: self._webhook_id,
                        CONF_API_KEY: self._api_key,
                        CONF_HA_DAEMON_URL: self._ha_daemon_url,
                        CONF_HA_GRUB_URL: self._ha_grub_url,
                        CONF_UPDATE_GRUB: self._update_grub,
                    },
                    session=async_create_clientsession(self.hass),
                )
                response_data = await client.async_pair(pin=pin)
            except GrubStationApiConflictError:
                _errors["base"] = "already_paired"
                webhook.async_unregister(self.hass, self._webhook_id)
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
        self._update_grub = True
        self._turn_off_action = None

        payload_dict = {
            "ha_daemon_url": ha_daemon_url,
            "webhook_id": self._webhook_id,
            "api_key": self._api_key,
            "ha_grub_url": f"{ha_grub_url}/api/grubstation/boot",
            "update_grub": True,
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
            CONF_IP_ADDRESS: self._ip_address,
            CONF_PORT: self._port,
            CONF_MAC: self._mac,
            CONF_WEBHOOK_ID: self._webhook_id,
            CONF_API_KEY: self._api_key,
            CONF_HA_DAEMON_URL: self._ha_daemon_url,
            CONF_HA_GRUB_URL: self._ha_grub_url,
            CONF_UPDATE_GRUB: self._update_grub,
            CONF_TURN_OFF_ACTION: self._turn_off_action,
            "hostname": self._hostname,
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

            port = SERVER_PORT
            api = getattr(self.hass.config, "api", None)
            if api and getattr(api, "port", None):
                port = api.port

            if not ha_daemon_url:
                ha_daemon_url = f"http://{ha_ip}:{port}"
            if not grub_url:
                grub_url = f"http://{ha_ip}:{port}"

        return ha_daemon_url, grub_url


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

            # Validate: daemonless hosts require a turn_off_action
            if new_data.get(CONF_DAEMONLESS) and not new_data[CONF_TURN_OFF_ACTION]:
                _errors[CONF_TURN_OFF_ACTION] = "turn_off_action_required_for_daemonless"
            else:
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=new_data,
                )
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
                }
            ),
            errors=_errors,
        )
