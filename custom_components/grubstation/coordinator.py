"""DataUpdateCoordinator for grubstation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GrubStationApiClientAuthenticationError, GrubStationApiClientError
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
        try:
            return await self.config_entry.runtime_data.client.async_get_status(
                daemon_token=self.config_entry.data.get(CONF_DAEMON_TOKEN)
            )
        except GrubStationApiClientAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except GrubStationApiClientError as exception:
            raise UpdateFailed(exception) from exception

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
