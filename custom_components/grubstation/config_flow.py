"""Config flow for GrubStation."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import aiohttp
from aiohttp import web
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.const import CONF_IP_ADDRESS, CONF_PIN, CONF_PORT, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import CONF_BOOT_OPTIONS, CONF_DAEMON_TOKEN, DOMAIN, LOGGER
from .helpers import normalize_mac

CONF_INTERFACE = "interface"


async def _async_temp_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    request: web.Request,
) -> web.Response:
    """Handle temporary webhook for initial sync during pairing."""
    return web.json_response({"status": "ok"})


class GrubStationFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GrubStation."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None
        self._port: int = 8081
        self._pin: str | None = None
        self._long_lived_token: str | None = None
        self._hostname: str | None = None
        self._interfaces: list[dict[str, Any]] = []

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> config_entries.ConfigFlowResult:
        """Handle zeroconf discovery."""
        LOGGER.debug("Received mDNS payload: %s", discovery_info)
        self._host = discovery_info.host
        self._port = discovery_info.port or 8081

        # Ignore already paired instances
        paired = discovery_info.properties.get("paired")
        if paired and str(paired).lower() in ("true", "1", "yes"):
            return self.async_abort(reason="already_configured")

        # Check if the host is already configured
        for entry in self._async_current_entries():
            if entry.data.get("host") == self._host:
                return self.async_abort(reason="already_configured")

        hostname = discovery_info.hostname.removesuffix(".") if discovery_info.hostname else ""
        name = f"{hostname} ({self._host})" if hostname else self._host
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_pin()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle manual user setup."""
        errors = {}
        if user_input is not None:
            self._host = user_input["host"]
            self._port = user_input["port"]

            for entry in self._async_current_entries():
                if entry.data.get("host") == self._host:
                    return self.async_abort(reason="already_configured")

            return await self.async_step_pin()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("host"): str,
                    vol.Required("port", default=8081): int,
                }
            ),
            errors=errors,
        )

    async def async_step_pin(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle the PIN authentication step."""
        errors = {}
        if user_input is not None:
            self._pin = user_input[CONF_PIN]

            session = async_get_clientsession(self.hass)
            url_verify = f"http://{self._host}:{self._port}/pair/verify"
            headers = {
                "Authorization": f"Bearer {self._pin}",
            }
            try:
                async with asyncio.timeout(10):
                    response_verify = await session.post(url_verify, headers=headers)
                    if response_verify.status == 401:
                        errors["base"] = "invalid_auth"
                    elif response_verify.status == 200:
                        data = await response_verify.json()
                        self._token = data.get("token")
                        self._hostname = data.get("hostname")
                        self._boot_options = data.get("boot_options", [])

                        # Query GET /interfaces
                        url_interfaces = f"http://{self._host}:{self._port}/interfaces"
                        headers_interfaces = {
                            "Authorization": f"Bearer {self._token}",
                        }
                        response_interfaces = await session.get(url_interfaces, headers=headers_interfaces)
                        if response_interfaces.status == 200:
                            self._interfaces = await response_interfaces.json()
                            if not self._interfaces:
                                errors["base"] = "no_physical_interfaces"
                            else:
                                return await self.async_step_interface()
                        else:
                            errors["base"] = "unknown"
                    else:
                        errors["base"] = "unknown"
            except TimeoutError, aiohttp.ClientError:
                LOGGER.error("Cannot connect to GrubStation daemon during pairing step")
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                LOGGER.exception("Unexpected error during pairing step: %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="pin",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PIN): str,
                }
            ),
            errors=errors,
        )

    async def async_step_interface(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle interface selection and registration step."""
        errors = {}
        if user_input is not None:
            selected_interface_name = user_input[CONF_INTERFACE]
            selected_interface = next(iface for iface in self._interfaces if iface["name"] == selected_interface_name)

            try:
                ha_url = get_url(self.hass)
            except Exception:  # noqa: BLE001
                ha_url = "http://homeassistant.local:8123"

            webhook_id = webhook.async_generate_id()
            api_key = secrets.token_hex(16)
            normalized_mac = normalize_mac(selected_interface["mac_address"])

            # Register temporary webhook to handle the initial sync call from the daemon
            webhook.async_register(
                self.hass,
                DOMAIN,
                "GrubStation Temp Webhook",
                webhook_id,
                _async_temp_webhook,
            )

            session = async_get_clientsession(self.hass)
            url_pair = f"http://{self._host}:{self._port}/pair"
            pair_headers = {
                "Authorization": f"Bearer {self._token}",
            }
            pair_payload = {
                "webhook_id": webhook_id,
                "api_key": api_key,
                "ha_url": ha_url,
                "update_grub": True,
                "interface": selected_interface["name"],
            }

            try:
                async with asyncio.timeout(10):
                    pair_response = await session.post(url_pair, headers=pair_headers, json=pair_payload)
                    if pair_response.status == 200:
                        await self.async_set_unique_id(normalized_mac)
                        self._abort_if_unique_id_configured()

                        return self.async_create_entry(
                            title=self._hostname or f"GrubStation ({self._host})",
                            data={
                                CONF_IP_ADDRESS: self._host,
                                CONF_PORT: self._port,
                                "hostname": self._hostname,
                                "mac": normalized_mac,
                                "ipv4": selected_interface.get("ip_address"),
                                CONF_DAEMON_TOKEN: self._token,
                                CONF_WEBHOOK_ID: webhook_id,
                                "api_key": api_key,
                                CONF_BOOT_OPTIONS: self._boot_options,
                            },
                        )
                    errors["base"] = "unknown"
            except TimeoutError, aiohttp.ClientError:
                LOGGER.error("Cannot connect to GrubStation daemon during registration step")
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                LOGGER.exception("Unexpected error during registration step: %s", err)
                errors["base"] = "unknown"
            finally:
                # Clean up the temporary webhook so the real entry setup can register it
                webhook.async_unregister(self.hass, webhook_id)

        interface_options = {
            iface["name"]: f"{iface['name']} - {iface['mac_address']} ({iface['ip_address']})"
            for iface in self._interfaces
        }

        return self.async_show_form(
            step_id="interface",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INTERFACE): vol.In(interface_options),
                }
            ),
            errors=errors,
        )
