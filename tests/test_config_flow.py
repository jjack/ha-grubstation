"""Tests for GrubStation config flow."""

from http import HTTPStatus
import ipaddress
from unittest.mock import AsyncMock, patch

import aiohttp

from custom_components.grubstation.const import DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.setup import async_setup_component


async def test_manual_user_flow(hass: HomeAssistant) -> None:
    """Test manual user flow config step and navigation to pin step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result_pin = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "192.168.1.100",
            "port": 8081,
        },
    )
    assert result_pin["type"] == "form"
    assert result_pin["step_id"] == "pin"


async def test_zeroconf_flow(hass: HomeAssistant) -> None:
    """Test zeroconf discovery step and navigation to pin step."""
    discovery_info = ZeroconfServiceInfo(
        ip_address=ipaddress.ip_address("192.168.1.100"),
        ip_addresses=[ipaddress.ip_address("192.168.1.100")],
        hostname="grubstation-daemon.local",
        port=8081,
        name="grubstation",
        properties={},
        type="_grubstation._tcp.local.",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=discovery_info,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "pin"
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["title_placeholders"] == {"name": "grubstation-daemon.local (192.168.1.100)"}


async def test_pin_auth_success(hass: HomeAssistant) -> None:
    """Test successful PIN authentication and config entry creation."""
    assert await async_setup_component(hass, "http", {})

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result_pin = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "192.168.1.100",
            "port": 8081,
        },
    )

    mock_verify_response = AsyncMock()
    mock_verify_response.status = HTTPStatus.OK
    mock_verify_response.json = AsyncMock(
        return_value={
            "success": True,
            "token": "test_daemon_token",
            "hostname": "grubstation-host",
            "os": "ubuntu",
            "boot_options": ["Ubuntu", "Windows"],
        }
    )

    mock_interfaces_response = AsyncMock()
    mock_interfaces_response.status = HTTPStatus.OK
    mock_interfaces_response.json = AsyncMock(
        return_value=[
            {
                "name": "eth0",
                "mac_address": "aa:bb:cc:dd:ee:ff",
                "ip_address": "192.168.1.100",
                "ip_addresses": ["192.168.1.100"],
            }
        ]
    )

    mock_pair_response = AsyncMock()
    mock_pair_response.status = HTTPStatus.OK

    with patch("custom_components.grubstation.config_flow.async_get_clientsession") as mock_get_session:
        session = AsyncMock()
        mock_get_session.return_value = session
        session.post = AsyncMock(side_effect=[mock_verify_response, mock_pair_response])
        session.get = AsyncMock(return_value=mock_interfaces_response)

        result_interface = await hass.config_entries.flow.async_configure(
            result_pin["flow_id"],
            {
                "pin": "123456",
            },
        )
        assert result_interface["type"] == "form"
        assert result_interface["step_id"] == "interface"

        result_create = await hass.config_entries.flow.async_configure(
            result_interface["flow_id"],
            {
                "interface": "eth0",
            },
        )

        assert result_create["type"] == "create_entry"
        assert result_create["title"] == "grubstation-host"
        assert result_create["data"]["ip_address"] == "192.168.1.100"
        assert result_create["data"]["port"] == 8081
        assert result_create["data"]["hostname"] == "grubstation-host"
        assert result_create["data"]["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result_create["data"]["ipv4"] == "192.168.1.100"
        assert "webhook_id" in result_create["data"]
        assert result_create["data"]["daemon_token"] == "test_daemon_token"


async def test_pin_auth_invalid(hass: HomeAssistant) -> None:
    """Test PIN authentication with invalid PIN."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result_pin = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "192.168.1.100",
            "port": 8081,
        },
    )

    mock_pair_response = AsyncMock()
    mock_pair_response.status = HTTPStatus.UNAUTHORIZED

    with patch("custom_components.grubstation.config_flow.async_get_clientsession") as mock_get_session:
        session = AsyncMock()
        session.post = AsyncMock(return_value=mock_pair_response)
        mock_get_session.return_value = session

        result_invalid = await hass.config_entries.flow.async_configure(
            result_pin["flow_id"],
            {
                "pin": "wrong_pin",
            },
        )
        assert result_invalid["type"] == "form"
        assert result_invalid["errors"] == {"base": "invalid_auth"}


async def test_pin_auth_cannot_connect(hass: HomeAssistant) -> None:
    """Test PIN authentication connection failure."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result_pin = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "192.168.1.100",
            "port": 8081,
        },
    )

    with patch("custom_components.grubstation.config_flow.async_get_clientsession") as mock_get_session:
        session = AsyncMock()
        session.post = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
        mock_get_session.return_value = session

        result_error = await hass.config_entries.flow.async_configure(
            result_pin["flow_id"],
            {
                "pin": "123456",
            },
        )
        assert result_error["type"] == "form"
        assert result_error["errors"] == {"base": "cannot_connect"}
