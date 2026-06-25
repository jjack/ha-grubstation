"""Tests for GrubStation API client."""

from typing import Any
from unittest.mock import MagicMock

from custom_components.grubstation.api import GrubStationApiClient


async def test_api_pair() -> None:
    """Test pairing API call."""
    response = MagicMock()
    response.status = 200

    async def mock_json() -> dict[str, bool]:
        return {"paired": True}

    response.json = mock_json

    async def mock_request(*args: Any, **kwargs: Any) -> MagicMock:
        return response

    session = MagicMock()
    session.request = mock_request

    client = GrubStationApiClient(
        config={
            "host": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": False,
            "webhook_id": "test_webhook",
            "api_key": "test_key",
            "ha_daemon_url": "http://127.0.0.1:8123",
            "ha_grub_url": "http://127.0.0.1:8123",
            "apply_config": True,
        },
        session=session,
    )

    result = await client.async_pair()
    assert result == {"paired": True}


async def test_api_unpair() -> None:
    """Test unpairing API call."""
    response = MagicMock()
    response.status = 200

    async def mock_json() -> dict[str, str]:
        return {"status": "unpaired"}

    response.json = mock_json

    last_headers = {}

    async def mock_request(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal last_headers
        last_headers = kwargs.get("headers", {})
        return response

    session = MagicMock()
    session.request = mock_request

    client = GrubStationApiClient(
        config={
            "host": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": False,
            "webhook_id": "test_webhook",
            "api_key": "test_key",
            "ha_daemon_url": "http://127.0.0.1:8123",
            "ha_grub_url": "http://127.0.0.1:8123",
            "apply_config": True,
        },
        session=session,
    )

    result = await client.async_unpair()
    assert result == {"status": "unpaired"}
    assert last_headers.get("Authorization") == "Bearer test_key"


async def test_api_get_status() -> None:
    """Test get status API call."""
    response = MagicMock()
    response.status = 200

    async def mock_json() -> dict[str, str]:
        return {
            "os": "Linux",
            "service_manager": "systemd",
            "status": "running",
            "version": "1.0.0",
        }

    response.json = mock_json

    last_headers = {}

    async def mock_request(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal last_headers
        last_headers = kwargs.get("headers", {})
        return response

    session = MagicMock()
    session.request = mock_request

    client = GrubStationApiClient(
        config={
            "host": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": False,
            "webhook_id": "test_webhook",
            "api_key": "test_key",
            "ha_daemon_url": "http://127.0.0.1:8123",
            "ha_grub_url": "http://127.0.0.1:8123",
            "apply_config": True,
        },
        session=session,
    )

    result = await client.async_get_status()
    assert result == {
        "os": "Linux",
        "service_manager": "systemd",
        "status": "running",
        "version": "1.0.0",
    }
    assert last_headers.get("Authorization") == "Bearer test_key"
