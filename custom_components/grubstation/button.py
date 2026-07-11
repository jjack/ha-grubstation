"""Button platform for grubstation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import wakeonlan

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import CONF_MAC

from .const import CONF_DAEMONLESS, CONF_WOL_BROADCAST, CONF_WOL_PORT, DEFAULT_WOL_BROADCAST, DEFAULT_WOL_PORT
from .entity import GrubStationEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrubStationDataUpdateCoordinator
    from .data import GrubStationConfigEntry

ENTITY_DESCRIPTIONS = (
    ButtonEntityDescription(
        key="grubstation",
        translation_key="wake_on_lan",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    if not entry.data.get(CONF_DAEMONLESS):
        return

    async_add_entities(
        GrubStationButton(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class GrubStationButton(GrubStationEntity, ButtonEntity):
    """grubstation button class."""

    def __init__(
        self,
        coordinator: GrubStationDataUpdateCoordinator,
        entity_description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_wake_on_lan"

    async def async_press(self) -> None:
        """Handle the button press."""
        mac = self.coordinator.config_entry.data.get(CONF_MAC)
        if mac:
            broadcast = self.coordinator.config_entry.data.get(CONF_WOL_BROADCAST, DEFAULT_WOL_BROADCAST)
            port = self.coordinator.config_entry.data.get(CONF_WOL_PORT, DEFAULT_WOL_PORT)
            await self.hass.async_add_executor_job(lambda: wakeonlan.wake(mac, host=broadcast, port=port))
        await self.coordinator.async_request_refresh()
