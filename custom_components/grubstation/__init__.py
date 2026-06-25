"""
Custom integration to integrate grubstation with Home Assistant.

For more details about this integration, please refer to
https://github.com/jjack/grubstation
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import GrubStationApiClient
from .const import DOMAIN, LOGGER
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


async def async_handle_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    request: web.Request,
) -> web.Response | None:
    """Handle webhook callback."""
    return web.json_response({"status": "ok"})


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
            config=entry.data,
            session=async_get_clientsession(hass),
        ),
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    # Register webhook
    webhook.async_register(
        hass,
        DOMAIN,
        "GrubStation Webhook",
        entry.data[CONF_WEBHOOK_ID],
        async_handle_webhook,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    if webhook_id := entry.data.get(CONF_WEBHOOK_ID):
        webhook.async_unregister(hass, webhook_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
) -> None:
    """Handle removal of an entry."""
    client = GrubStationApiClient(
        config=entry.data,
        session=async_get_clientsession(hass),
    )
    try:
        await client.async_unpair()
    except Exception as exception:  # noqa: BLE001
        LOGGER.warning("Failed to unpair from GrubStation: %s", exception)
