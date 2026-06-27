"""Fixtures for GrubStation integration tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in Home Assistant."""
    return


@pytest.fixture(autouse=True)
def mock_zeroconf_setup():
    """Mock zeroconf setup to prevent socket blocked errors."""
    with patch("homeassistant.components.zeroconf.async_setup", return_value=True):
        yield


@pytest.fixture(autouse=True)
def mock_api_client(request):
    """Mock GrubStationApiClient methods to prevent real network calls."""
    if "test_api" in request.node.name or "test_api" in str(request.node.fspath):
        yield
        return

    with (
        patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_get_status",
            return_value={
                "os": "Linux",
                "service_manager": "systemd",
                "status": "running",
                "version": "1.0.0",
            },
        ),
        patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_get_data",
            return_value={"status": "ok"},
        ),
    ):
        yield
