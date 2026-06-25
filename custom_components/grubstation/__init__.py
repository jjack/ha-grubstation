"""
Custom integration to integrate grubstation with Home Assistant.

For more details about this integration, please refer to
https://github.com/jjack/grubstation
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_MAC, CONF_PORT, CONF_WEBHOOK_ID, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import GrubStationApiClient
from .const import CONF_APPLY_CONFIG, CONF_DAEMONLESS, CONF_HA_DAEMON_URL, CONF_HA_GRUB_URL, DOMAIN, LOGGER
from .coordinator import BlueprintDataUpdateCoordinator
from .data import GrubStationData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import GrubStationConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    coordinator = BlueprintDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=timedelta(hours=1),
    )
    entry.runtime_data = GrubStationData(
        client=GrubStationApiClient(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            mac=entry.data.get(CONF_MAC),
            daemonless=entry.data[CONF_DAEMONLESS],
            webhook_id=entry.data.get(CONF_WEBHOOK_ID),
            api_key=entry.data.get(CONF_API_KEY),
            ha_daemon_url=entry.data.get(CONF_HA_DAEMON_URL),
            ha_grub_url=entry.data.get(CONF_HA_GRUB_URL),
            apply_config=entry.data.get(CONF_APPLY_CONFIG, True),
            session=async_get_clientsession(hass),
        ),
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
