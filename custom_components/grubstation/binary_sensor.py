"""Binary sensor platform for grubstation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .const import ATTR_OS, ATTR_SERVICE_MANAGER, ATTR_VERSION
from .entity import GrubStationEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrubStationDataUpdateCoordinator
    from .data import GrubStationConfigEntry

ENTITY_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="grubstation",
        translation_key="agent_status",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary_sensor platform."""
    async_add_entities(
        GrubStationBinarySensor(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class GrubStationBinarySensor(GrubStationEntity, BinarySensorEntity):
    """grubstation binary_sensor class."""

    def __init__(
        self,
        coordinator: GrubStationDataUpdateCoordinator,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary_sensor class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{entity_description.key}"

    @property
    def is_on(self) -> bool:
        """Return true if the binary_sensor is on."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}
        return {
            ATTR_OS: self.coordinator.data.get("os"),
            ATTR_SERVICE_MANAGER: self.coordinator.data.get("service_manager"),
            ATTR_VERSION: self.coordinator.data.get("version"),
        }
