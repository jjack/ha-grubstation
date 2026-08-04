"""Select platform for grubstation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_BOOT_OPTIONS, DEFAULT_BOOT_OPTION
from .entity import GrubStationEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GrubStationDataUpdateCoordinator
    from .data import GrubStationConfigEntry

ENTITY_DESCRIPTIONS = (
    SelectEntityDescription(
        key="boot_option",
        translation_key="next_boot_option",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrubStationConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    async_add_entities(
        GrubStationSelect(
            coordinator=entry.runtime_data.coordinator,
            entity_description=entity_description,
        )
        for entity_description in ENTITY_DESCRIPTIONS
    )


class GrubStationSelect(GrubStationEntity, RestoreEntity, SelectEntity):
    """grubstation select class."""

    def __init__(
        self,
        coordinator: GrubStationDataUpdateCoordinator,
        entity_description: SelectEntityDescription,
    ) -> None:
        """Initialize the select class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{entity_description.key}"

    @property
    def options(self) -> list[str]:
        """Return a list of available options."""
        daemons = self.coordinator.config_entry.data.get("daemons") or {}
        if daemons:
            all_opts = set()
            for d_info in daemons.values():
                opts = d_info.get(CONF_BOOT_OPTIONS) or []
                all_opts.update(opts)
            boot_options = sorted(all_opts)
        else:
            boot_options = self.coordinator.config_entry.data.get(CONF_BOOT_OPTIONS) or []
        return [DEFAULT_BOOT_OPTION] + [opt for opt in boot_options if opt != DEFAULT_BOOT_OPTION]

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option."""
        if hasattr(self.coordinator.config_entry, "runtime_data"):
            return self.coordinator.config_entry.runtime_data.next_boot
        return DEFAULT_BOOT_OPTION

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if hasattr(self.coordinator.config_entry, "runtime_data"):
            self.coordinator.config_entry.runtime_data.next_boot = option
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in self.options:
                if hasattr(self.coordinator.config_entry, "runtime_data"):
                    self.coordinator.config_entry.runtime_data.next_boot = last_state.state
