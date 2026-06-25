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

    from .coordinator import BlueprintDataUpdateCoordinator
    from .data import GrubStationConfigEntry

ENTITY_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="grubstation",
        name="GrubStation Binary Sensor",
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
        coordinator: BlueprintDataUpdateCoordinator,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary_sensor class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_is_on = False
        self._extra_attributes: dict[str, Any] = {}

    @property
    def should_poll(self) -> bool:
        """Return True to enable polling."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true if the binary_sensor is on."""
        return self._attr_is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self._extra_attributes

    async def async_update(self) -> None:
        """Update entity state by polling async_get_status."""
        try:
            status = await self.coordinator.config_entry.runtime_data.client.async_get_status()
            self._attr_is_on = status.get("status") == "running"
            self._extra_attributes = {
                ATTR_OS: status.get("os"),
                ATTR_SERVICE_MANAGER: status.get("service_manager"),
                ATTR_VERSION: status.get("version"),
            }
        except Exception:  # noqa: BLE001
            self._attr_is_on = False
            self._extra_attributes = {}
