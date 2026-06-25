"""DataUpdateCoordinator for grubstation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    GrubStationApiClientAuthenticationError,
    GrubStationApiClientError,
)

if TYPE_CHECKING:
    from .data import GrubStationConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class BlueprintDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: GrubStationConfigEntry

    async def _async_update_data(self) -> Any:
        """Update data via library."""
        try:
            return await self.config_entry.runtime_data.client.async_get_data()
        except GrubStationApiClientAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except GrubStationApiClientError as exception:
            raise UpdateFailed(exception) from exception
