"""Switch platform for grubstation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import wakeonlan

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import CONF_MAC

from .const import CONF_DAEMON_TOKEN, CONF_DAEMONLESS, CONF_TURN_OFF_ACTION
from .entity import GrubStationEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrubStationDataUpdateCoordinator
    from .data import GrubStationConfigEntry

ENTITY_DESCRIPTIONS = (
    SwitchEntityDescription(
        key="grubstation",
        translation_key="power",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    async_add_entities(
        GrubStationSwitch(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class GrubStationSwitch(GrubStationEntity, SwitchEntity):
    """grubstation switch class."""

    def __init__(
        self,
        coordinator: GrubStationDataUpdateCoordinator,
        entity_description: SwitchEntityDescription,
    ) -> None:
        """Initialize the switch class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_power"

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self.coordinator.last_update_success

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the switch."""
        mac = self.coordinator.config_entry.data.get(CONF_MAC)
        if mac:
            await self.hass.async_add_executor_job(wakeonlan.wake, mac)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the switch."""
        turn_off_action = self.coordinator.config_entry.data.get(CONF_TURN_OFF_ACTION)
        if turn_off_action and "." in turn_off_action:
            domain, service = turn_off_action.split(".", 1)
            await self.hass.services.async_call(domain, service, {})
        elif not self.coordinator.config_entry.data.get(CONF_DAEMONLESS):
            await self.coordinator.config_entry.runtime_data.client.async_shutdown(
                daemon_token=self.coordinator.config_entry.data.get(CONF_DAEMON_TOKEN)
            )
        await self.coordinator.async_request_refresh()
