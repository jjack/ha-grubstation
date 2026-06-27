"""GrubStationEntity class."""

from __future__ import annotations

from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import GrubStationDataUpdateCoordinator
from .helpers import format_display_name


class GrubStationEntity(CoordinatorEntity[GrubStationDataUpdateCoordinator]):
    """GrubStationEntity class."""

    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: GrubStationDataUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.config_entry.entry_id

        host = coordinator.config_entry.data.get(CONF_IP_ADDRESS)
        hostname = coordinator.config_entry.data.get("hostname")
        device_name = format_display_name(host, hostname)

        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.domain,
                    coordinator.config_entry.entry_id,
                ),
            },
            name=device_name,
        )
