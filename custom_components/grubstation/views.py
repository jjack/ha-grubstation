"""Views for the GrubStation custom component."""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.helpers.http import HomeAssistantView

from .const import DEFAULT_BOOT_OPTION, DOMAIN
from .helpers import normalize_mac

LOGGER = logging.getLogger(__package__)


class GrubStationConfigView(HomeAssistantView):
    """View to serve the next boot option to GRUB."""

    url = "/api/grubstation/{mac_address}"
    name = "api:grubstation:mac"
    requires_auth = False  # Grub can't auth easily

    async def get(self, request: web.Request, mac_address: str) -> web.Response:
        """Handle GRUB's request for the next boot option."""

        # Find the config entry matching this MAC address
        hass = request.app["hass"]
        matching_entry = None
        mac_address_norm = normalize_mac(mac_address)
        for entry in hass.config_entries.async_entries(DOMAIN):
            entry_mac = entry.data.get("mac")
            if entry_mac:
                entry_mac_norm = normalize_mac(entry_mac)
                if entry_mac_norm == mac_address_norm:
                    matching_entry = entry
                    break

        if not matching_entry:
            return web.Response(text="Not Found", status=404)

        token = request.query.get("token")
        if token:
            if matching_entry.data.get(CONF_WEBHOOK_ID) != token:
                return web.Response(text="Unauthorized", status=401)

        next_boot = DEFAULT_BOOT_OPTION
        if hasattr(matching_entry, "runtime_data"):
            next_boot = matching_entry.runtime_data.next_boot or DEFAULT_BOOT_OPTION
            if token:
                matching_entry.runtime_data.next_boot = DEFAULT_BOOT_OPTION
                # Trigger updates
                matching_entry.runtime_data.coordinator.async_set_updated_data(
                    matching_entry.runtime_data.coordinator.data or {}
                )

        return web.Response(text=next_boot)
