"""Custom types for grubstation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import GrubStationApiClient
    from .coordinator import GrubStationDataUpdateCoordinator


type GrubStationConfigEntry = ConfigEntry[GrubStationData]


@dataclass
class GrubStationData:
    """Data for the GrubStation integration."""

    client: GrubStationApiClient
    coordinator: GrubStationDataUpdateCoordinator
    integration: Integration
    next_boot: str = "default"
