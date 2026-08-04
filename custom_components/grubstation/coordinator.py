"""DataUpdateCoordinator for grubstation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GrubStationApiClient, GrubStationApiClientAuthenticationError, GrubStationApiClientError
from .const import ATTR_VERSION, CONF_DAEMON_TOKEN, CONF_DAEMONLESS, CONF_HOSTNAME, DEFAULT_DAEMON_PORT, DOMAIN
from .helpers import format_display_name

if TYPE_CHECKING:
    from .data import GrubStationConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class GrubStationDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: GrubStationConfigEntry

    async def _async_update_data(self) -> Any:
        """Update data via library."""
        if self.config_entry.data.get(CONF_DAEMONLESS):
            return self.data

        daemons = self.config_entry.data.get("daemons") or {}
        if not daemons:
            # Fallback to single client
            try:
                return await self.config_entry.runtime_data.client.async_get_status(
                    daemon_token=self.config_entry.data.get(CONF_DAEMON_TOKEN)
                )
            except GrubStationApiClientAuthenticationError as exception:
                raise ConfigEntryAuthFailed(exception) from exception
            except GrubStationApiClientError as exception:
                raise UpdateFailed(exception) from exception

        combined_daemons = {}
        for os_name, d_info in daemons.items():
            client = GrubStationApiClient(
                ip_address=d_info[CONF_IP_ADDRESS],
                port=d_info[CONF_PORT],
                session=async_get_clientsession(self.hass),
            )
            try:
                status = await client.async_get_status(daemon_token=d_info[CONF_DAEMON_TOKEN])
                combined_daemons[os_name] = {
                    **status,
                    "connected": True,
                }
            except Exception:  # noqa: BLE001
                # Inactive OS daemon will fail to connect; treat as offline
                combined_daemons[os_name] = {
                    "connected": False,
                    "status": "stopped",
                    "os": os_name.capitalize(),
                }

        # Find currently active OS daemon (if any)
        active_status = {}
        for d_status in combined_daemons.values():
            if d_status.get("connected"):
                active_status = d_status
                break

        return {
            "daemons": combined_daemons,
            "status": active_status.get("status", "stopped"),
            "os": active_status.get("os"),
            "service_manager": active_status.get("service_manager"),
            "version": active_status.get("version"),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        host = self.config_entry.data.get(CONF_IP_ADDRESS)
        hostname = self.config_entry.data.get(CONF_HOSTNAME)
        port = self.config_entry.data.get(CONF_PORT) or DEFAULT_DAEMON_PORT
        sw_version = self.data.get(ATTR_VERSION) if self.data else None
        mac = self.config_entry.data.get(CONF_MAC)

        device_info = DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=format_display_name(host, hostname),
            sw_version=sw_version,
            manufacturer="GrubStation",
            model="Boot Selection and Wake On Lan",
            configuration_url=f"http://{host}:{port}/status",
        )
        if mac:
            device_info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
        return device_info
