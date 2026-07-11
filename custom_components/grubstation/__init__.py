"""Custom integration to integrate grubstation with Home Assistant.

For more details about this integration, please refer to
https://github.com/jjack/grubstation
"""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, CONF_WEBHOOK_ID, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import GrubStationApiClient
from .const import CONF_BOOT_OPTIONS, CONF_DAEMON_TOKEN, DOMAIN, LOGGER
from .coordinator import GrubStationDataUpdateCoordinator
from .data import GrubStationData
from .views import GrubStationConfigView

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import GrubStationConfigEntry

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.SELECT,
]


async def async_handle_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    request: web.Request,
) -> web.Response | None:
    """Handle webhook callback."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"status": "error", "message": "Invalid JSON"}, status=HTTPStatus.BAD_REQUEST)

    # Find the config entry matching this webhook_id
    entry = None
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_WEBHOOK_ID) == webhook_id:
            entry = e
            break

    if not entry:
        return web.json_response({"status": "error", "message": "Entry not found"}, status=HTTPStatus.NOT_FOUND)

    # Process payload
    # 1. Update boot options if provided
    if "boot_options" in payload:
        boot_options = payload["boot_options"]
        new_data = dict(entry.data)
        new_data[CONF_BOOT_OPTIONS] = boot_options
        hass.config_entries.async_update_entry(entry, data=new_data)

    # 2. Update status/coordinator data if provided
    if hasattr(entry, "runtime_data") and ("status" in payload or "os" in payload):
        current_data = entry.runtime_data.coordinator.data or {}
        merged_data = {**current_data, **payload}
        entry.runtime_data.coordinator.async_set_updated_data(merged_data)

    return web.json_response({"status": "ok"})


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    coordinator = GrubStationDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=timedelta(seconds=60),
    )
    entry.runtime_data = GrubStationData(
        client=GrubStationApiClient(
            ip_address=entry.data[CONF_IP_ADDRESS],
            port=entry.data[CONF_PORT],
            session=async_get_clientsession(hass),
        ),
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # Register view if not already registered
    if "view_registered" not in hass.data.setdefault(DOMAIN, {}):
        hass.http.register_view(GrubStationConfigView())
        hass.data[DOMAIN]["view_registered"] = True

    # Run refresh but don't fail setup if the daemon is offline during startup
    await coordinator.async_refresh()

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
        ip_address=entry.data[CONF_IP_ADDRESS],
        port=entry.data[CONF_PORT],
        session=async_get_clientsession(hass),
    )
    try:
        if daemon_token := entry.data.get(CONF_DAEMON_TOKEN):
            await client.async_unpair(daemon_token=daemon_token)
    except Exception as exception:  # noqa: BLE001
        LOGGER.warning("Failed to unpair from GrubStation: %s", exception)
