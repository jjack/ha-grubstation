"""Tests for GrubStation config flow."""

from unittest.mock import patch

from custom_components.grubstation.api import GrubStationApiInvalidPinError, GrubStationApiPinRequiredError
from custom_components.grubstation.const import DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant


async def test_config_flow(hass: HomeAssistant) -> None:
    """Test the config flow user and pairing steps."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Fill host info, port, mac, and daemonless flag
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": False,
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "pairing"

    # Submit pairing step, which generates credentials and calls pairing API
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        return_value={"paired": True},
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {},
        )
        assert result3["type"] == "create_entry"
        assert result3["title"] == "GrubStation (127.0.0.1)"


async def test_config_flow_daemonless_requires_mac(hass: HomeAssistant) -> None:
    """Test that daemonless mode requires a MAC address."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Submit user step with daemonless=True but empty mac address
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "127.0.0.1",
            "port": 8081,
            "mac": "",
            "daemonless": True,
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "user"
    assert "mac" in result2["errors"]


async def test_config_flow_pin_required_and_invalid_and_success(
    hass: HomeAssistant,
) -> None:
    """Test config flow when PIN is required, then invalid, then correct."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # 1. Submit user details
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": False,
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "pairing"

    # 2. Submit pairing. Mock it to raise GrubStationApiPinRequiredError
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        side_effect=GrubStationApiPinRequiredError("PIN is required"),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {},
        )
    assert result3["type"] == "form"
    assert result3["step_id"] == "pin"

    # 3. Submit invalid PIN. Mock it to raise GrubStationApiInvalidPinError
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        side_effect=GrubStationApiInvalidPinError("Invalid PIN entered"),
    ):
        result4 = await hass.config_entries.flow.async_configure(
            result3["flow_id"],
            {"pin": "wrong_pin"},
        )
    assert result4["type"] == "form"
    assert result4["step_id"] == "pin"
    assert result4["errors"] == {"base": "invalid_pin"}

    # 4. Submit valid PIN. Mock it to return success response
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        return_value={
            "paired": True,
            "mac": "aa:bb:cc:dd:ee:ff",
            "boot_options": ["linux"],
        },
    ) as mock_pair:
        result5 = await hass.config_entries.flow.async_configure(
            result4["flow_id"],
            {"pin": "123456"},
        )
    assert result5["type"] == "create_entry"
    assert result5["title"] == "GrubStation (127.0.0.1)"
    mock_pair.assert_called_once_with(pin="123456")


async def test_config_flow_pin_connection_error(hass: HomeAssistant) -> None:
    """Test config flow when PIN step encounters a connection error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    # Fill user details
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": False,
        },
    )
    # Move to PIN step
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        side_effect=GrubStationApiPinRequiredError("PIN is required"),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {},
        )
    assert result3["type"] == "form"
    assert result3["step_id"] == "pin"

    # Submit invalid PIN resulting in connection error
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        side_effect=Exception("Connection lost"),
    ):
        result4 = await hass.config_entries.flow.async_configure(
            result3["flow_id"],
            {"pin": "123456"},
        )
    assert result4["type"] == "form"
    assert result4["step_id"] == "pin"
    assert result4["errors"] == {"base": "connection"}
