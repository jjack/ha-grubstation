"""Tests for GrubStation API client."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.grubstation.api import (
    GrubStationApiClient,
    GrubStationApiInvalidPinError,
    GrubStationApiPinRequiredError,
)


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
        ip_address="127.0.0.1",
        port=8081,
        session=session,
    )

    result = await client.async_pair(
        webhook_id="test_webhook",
        api_key="test_key",
        ha_daemon_url="http://127.0.0.1:8123",
        ha_grub_url="http://127.0.0.1:8123",
        update_grub=True,
    )
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
        ip_address="127.0.0.1",
        port=8081,
        session=session,
    )

    result = await client.async_unpair(daemon_token="test_token")
    assert result == {"status": "unpaired"}
    assert last_headers.get("Authorization") == "Bearer test_token"


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
        ip_address="127.0.0.1",
        port=8081,
        session=session,
    )

    result = await client.async_get_status(daemon_token="test_token")
    assert result == {
        "os": "Linux",
        "service_manager": "systemd",
        "status": "running",
        "version": "1.0.0",
    }
    assert last_headers.get("Authorization") == "Bearer test_token"


async def test_api_pair_pin_required() -> None:
    """Test pairing API call when PIN code is required."""
    response = MagicMock()
    response.status = 401

    async def mock_json() -> dict[str, str]:
        return {"error": "pin_required"}

    response.json = mock_json

    async def mock_request(*args: Any, **kwargs: Any) -> MagicMock:
        return response

    session = MagicMock()
    session.request = mock_request

    client = GrubStationApiClient(
        ip_address="127.0.0.1",
        port=8081,
        session=session,
    )

    with pytest.raises(GrubStationApiPinRequiredError):
        await client.async_pair(
            webhook_id="test_webhook",
            api_key="test_key",
            ha_daemon_url="http://127.0.0.1:8123",
            ha_grub_url="http://127.0.0.1:8123",
            update_grub=True,
        )


async def test_api_pair_invalid_pin() -> None:
    """Test pairing API call when entered PIN code is invalid."""
    response = MagicMock()
    response.status = 401

    async def mock_json() -> dict[str, str]:
        return {"error": "invalid_pin"}

    response.json = mock_json

    async def mock_request(*args: Any, **kwargs: Any) -> MagicMock:
        return response

    session = MagicMock()
    session.request = mock_request

    client = GrubStationApiClient(
        ip_address="127.0.0.1",
        port=8081,
        session=session,
    )

    with pytest.raises(GrubStationApiInvalidPinError):
        await client.async_pair(
            pin="123456",
            webhook_id="test_webhook",
            api_key="test_key",
            ha_daemon_url="http://127.0.0.1:8123",
            ha_grub_url="http://127.0.0.1:8123",
            update_grub=True,
        )


async def test_api_pair_with_pin_success() -> None:
    """Test pairing API call succeeds with correct PIN."""
    response = MagicMock()
    response.status = 200

    async def mock_json() -> dict[str, Any]:
        return {
            "paired": True,
            "mac": "aa:bb:cc:dd:ee:ff",
            "boot_options": ["linux", "windows"],
        }

    response.json = mock_json

    last_data = None
    last_headers = None

    async def mock_request(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal last_data, last_headers
        last_data = kwargs.get("json")
        last_headers = kwargs.get("headers")
        return response

    session = MagicMock()
    session.request = mock_request

    client = GrubStationApiClient(
        ip_address="127.0.0.1",
        port=8081,
        session=session,
    )

    result = await client.async_pair(
        pin="123456",
        webhook_id="test_webhook",
        api_key="test_key",
        ha_daemon_url="http://127.0.0.1:8123",
        ha_grub_url="http://127.0.0.1:8123",
        update_grub=True,
    )
    assert result == {
        "paired": True,
        "mac": "aa:bb:cc:dd:ee:ff",
        "boot_options": ["linux", "windows"],
    }
    assert last_data is not None
    assert last_headers is not None
    assert last_headers.get("Authorization") == "Bearer 123456"
