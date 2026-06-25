"""Tests for GrubStation config flow."""

from unittest.mock import patch

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
