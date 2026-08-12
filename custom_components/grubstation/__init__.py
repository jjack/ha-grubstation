"""Custom integration to integrate grubstation with Home Assistant.

For more details about this integration, please refer to
https://github.com/jjack/grubstation
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, CONF_WEBHOOK_ID, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import GrubStationApiClient
from .const import CONF_BOOT_OPTIONS, CONF_DAEMON_TOKEN, CONF_DAEMONLESS, DOMAIN, LOGGER, SCAN_INTERVAL
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

    os_name = payload.get("os")

    # Process payload
    # 1. Update boot options if provided
    if "boot_options" in payload:
        boot_options = payload["boot_options"]
        new_data = dict(entry.data)
        if os_name and "daemons" in new_data:
            daemons = dict(new_data["daemons"])
            os_key = os_name.lower()
            if os_key in daemons:
                d_info = dict(daemons[os_key])
                d_info["boot_options"] = boot_options
                daemons[os_key] = d_info
                new_data["daemons"] = daemons
        new_data[CONF_BOOT_OPTIONS] = boot_options
        hass.config_entries.async_update_entry(entry, data=new_data)

    # 2. Update status/coordinator data if provided
    if hasattr(entry, "runtime_data") and ("status" in payload or "os" in payload):
        current_data = entry.runtime_data.coordinator.data or {}
        if os_name and "daemons" in current_data:
            daemons = dict(current_data.get("daemons", {}))
            os_key = os_name.lower()
            d_status = dict(daemons.get(os_key, {}))
            d_status.update(payload)
            d_status["connected"] = payload.get("status") == "running"
            daemons[os_key] = d_status

            merged_data = {**current_data, "daemons": daemons}
            if payload.get("status") == "running" or current_data.get("os") == os_name:
                merged_data.update(
                    {
                        "status": payload.get("status", "stopped"),
                        "os": os_name,
                        "service_manager": payload.get("service_manager", d_status.get("service_manager")),
                        "version": payload.get("version", d_status.get("version")),
                    }
                )
        else:
            merged_data = {**current_data, **payload}
        entry.runtime_data.coordinator.async_set_updated_data(merged_data)

    return web.json_response({"status": "ok"})


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    is_daemonless = entry.data.get(CONF_DAEMONLESS, False)
    coordinator = GrubStationDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=None if is_daemonless else SCAN_INTERVAL,
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
    ip_address = entry.data.get(CONF_IP_ADDRESS) or entry.data.get("host")
    port = entry.data.get(CONF_PORT) or 8081
    if not ip_address:
        LOGGER.warning("Could not find IP address for GrubStation entry, skipping unpair request")
        return

    client = GrubStationApiClient(
        ip_address=ip_address,
        port=port,
        session=async_get_clientsession(hass),
    )
    try:
        if daemon_token := entry.data.get(CONF_DAEMON_TOKEN):
            await client.async_unpair(daemon_token=daemon_token)
    except Exception as exception:  # noqa: BLE001
        LOGGER.warning("Failed to unpair from GrubStation: %s", exception)
