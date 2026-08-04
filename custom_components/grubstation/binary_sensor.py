"""Binary sensor platform for grubstation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.helpers.device_registry import DeviceInfo

from .const import ATTR_OS, ATTR_SERVICE_MANAGER, ATTR_VERSION, CONF_HOSTNAME, DOMAIN
from .entity import GrubStationEntity
from .helpers import format_display_name

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrubStationDataUpdateCoordinator
    from .data import GrubStationConfigEntry

ENTITY_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="grubstation",
        translation_key="daemon_status",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary_sensor platform."""
    daemons = entry.data.get("daemons") or {}
    if not daemons:
        # Fallback to single OS sensor
        async_add_entities(
            GrubStationBinarySensor(
                coordinator=entry.runtime_data.coordinator,
                entity_description=entity_description,
            )
            for entity_description in ENTITY_DESCRIPTIONS
        )
        return

    async_add_entities(
        GrubStationBinarySensor(
            coordinator=entry.runtime_data.coordinator,
            entity_description=BinarySensorEntityDescription(
                key=f"grubstation_{os_name}",
                name="Daemon Status",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
            os_name=os_name,
        )
        for os_name in daemons
    )


class GrubStationBinarySensor(GrubStationEntity, BinarySensorEntity):
    """grubstation binary_sensor class."""

    def __init__(
        self,
        coordinator: GrubStationDataUpdateCoordinator,
        entity_description: BinarySensorEntityDescription,
        os_name: str | None = None,
    ) -> None:
        """Initialize the binary_sensor class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self.os_name = os_name
        if os_name:
            self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{os_name}_{entity_description.key}"
        else:
            self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{entity_description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        if self.os_name:
            entry = self.coordinator.config_entry
            host = entry.data.get(CONF_IP_ADDRESS)
            hostname = entry.data.get(CONF_HOSTNAME)
            machine_name = format_display_name(host, hostname)
            os_display = self.os_name.capitalize()

            return DeviceInfo(
                identifiers={(DOMAIN, f"{entry.entry_id}_{self.os_name}")},
                name=f"{machine_name} {os_display}",
                via_device=(DOMAIN, entry.entry_id),
                manufacturer="GrubStation",
                model=f"OS Environment ({os_display})",
            )
        return super().device_info

    @property
    def is_on(self) -> bool:
        """Return true if the binary_sensor is on."""
        if self.os_name:
            daemons_data = self.coordinator.data.get("daemons", {}) if self.coordinator.data else {}
            daemon_data = daemons_data.get(self.os_name, {})
            return daemon_data.get("connected", False)
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if self.os_name:
            daemons_data = self.coordinator.data.get("daemons", {}) if self.coordinator.data else {}
            daemon_data = daemons_data.get(self.os_name, {})
            return {
                ATTR_OS: daemon_data.get("os"),
                ATTR_SERVICE_MANAGER: daemon_data.get("service_manager"),
                ATTR_VERSION: daemon_data.get("version"),
            }
        if not self.coordinator.data:
            return {}
        return {
            ATTR_OS: self.coordinator.data.get("os"),
            ATTR_SERVICE_MANAGER: self.coordinator.data.get("service_manager"),
            ATTR_VERSION: self.coordinator.data.get("version"),
        }
