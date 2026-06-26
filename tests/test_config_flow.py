"""Tests for GrubStation config flow."""

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grubstation.api import (
    GrubStationApiConflictError,
    GrubStationApiInvalidPinError,
    GrubStationApiPinRequiredError,
)
from custom_components.grubstation.const import DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.setup import async_setup_component


async def test_config_flow(hass: HomeAssistant) -> None:
    """Test the config flow user and pairing steps."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Fill host info, port, mac, and daemonless flag
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "ip_address": "127.0.0.1",
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
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "",
            "daemonless": True,
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "user"
    assert "mac" in result2["errors"]


async def test_config_flow_invalid_ip(hass: HomeAssistant) -> None:
    """Test that config flow rejects a host that is not an IP address."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Submit user step with a non-IP host address
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "ip_address": "grubstation.local",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": False,
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "user"
    assert result2["errors"] == {"ip_address": "invalid_ip"}


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
            "ip_address": "127.0.0.1",
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
            "ip_address": "127.0.0.1",
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


async def test_config_flow_daemonless(hass: HomeAssistant, hass_client) -> None:
    # Setup HTTP and webhook components first so hass.http is not None
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Fill host info, port, mac, daemonless=True, and turn_off_action
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "ip_address": "192.168.1.10",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": True,
            "turn_off_action": "script.shutdown_my_pc",
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "daemonless_onboarding"

    # Submit without running the CLI command/callback first -> should show error
    result3 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {},
    )
    assert result3["type"] == "form"
    assert result3["step_id"] == "daemonless_onboarding"
    assert result3["errors"] == {"base": "waiting_for_device_callback"}

    # Simulate the remote machine sending the pairing webhook callback
    # We find the flow handler instance to get the generated webhook ID
    flow_id = result["flow_id"]
    flow = hass.config_entries.flow._progress[flow_id]
    webhook_id = flow._webhook_id

    client = await hass_client()
    resp = await client.post(
        f"/api/webhook/{webhook_id}",
        json={
            "action": "update_boot_options",
            "boot_options": ["Ubuntu", "Windows Boot Manager"],
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data == {"status": "ok"}

    # Now click Submit again -> should succeed and create the entry
    result4 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {},
    )
    assert result4["type"] == "create_entry"
    assert result4["title"] == "GrubStation (192.168.1.10) [Manual]"
    assert result4["data"]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert result4["data"]["boot_options"] == [
        "Ubuntu",
        "Windows Boot Manager",
    ]


async def test_config_flow_daemonless_requires_turn_off_action(hass: HomeAssistant) -> None:
    """Test that daemonless mode requires a turn_off_action."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Submit with daemonless=True but no turn_off_action
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "ip_address": "192.168.1.10",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "daemonless": True,
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "user"
    assert "turn_off_action" in result2["errors"]


async def test_config_flow_zeroconf(hass: HomeAssistant) -> None:
    """Test the config flow via zeroconf."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    discovery_info = ZeroconfServiceInfo(
        ip_address="127.0.0.1",
        ip_addresses=["127.0.0.1"],
        hostname="grubstation.local.",
        name="GrubStation",
        port=8081,
        type="_grubstation._tcp.local.",
        properties={
            "mac": "aa:bb:cc:dd:ee:ff",
            "paired": "false",
            "address": "127.0.0.1",
        },
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=discovery_info,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "zeroconf_confirm"

    # Verify context title_placeholders is populated for discovery page
    flow = hass.config_entries.flow._progress[result["flow_id"]]
    assert flow.context["title_placeholders"] == {"name": "127.0.0.1 (grubstation.local)"}

    # Submit pairing step, which generates credentials and calls pairing API
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        return_value={"paired": True},
    ) as mock_pair:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "pin": "123456",
                "update_grub": True,
                "ha_daemon_url": "https://my-ha.duckdns.org:8123",
                "ha_grub_url": "http://10.15.0.5:8123",
            },
        )
        assert result2["type"] == "create_entry"
        assert result2["title"] == "grubstation.local (127.0.0.1)"
        assert result2["data"]["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result2["data"]["ip_address"] == "127.0.0.1"
        assert result2["data"]["ha_daemon_url"] == "https://my-ha.duckdns.org:8123"
        assert result2["data"]["ha_grub_url"] == "http://10.15.0.5:8123"
        assert result2["data"]["update_grub"] is True
        mock_pair.assert_called_once_with(pin="123456")


async def test_config_flow_zeroconf_already_configured(hass: HomeAssistant) -> None:
    """Test that zeroconf flow aborts if already configured."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
        },
        unique_id="aa:bb:cc:dd:ee:ff",
    )
    entry.add_to_hass(hass)

    discovery_info = ZeroconfServiceInfo(
        ip_address="127.0.0.1",
        ip_addresses=["127.0.0.1"],
        hostname="grubstation.local.",
        name="GrubStation",
        port=8081,
        type="_grubstation._tcp.local.",
        properties={
            "mac": "aa:bb:cc:dd:ee:ff",
            "paired": "false",
            "address": "127.0.0.1",
        },
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=discovery_info,
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_config_flow_zeroconf_already_paired(hass: HomeAssistant) -> None:
    """Test that zeroconf flow displays already_paired error on conflict."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    discovery_info = ZeroconfServiceInfo(
        ip_address="127.0.0.1",
        ip_addresses=["127.0.0.1"],
        hostname="grubstation.local.",
        name="GrubStation",
        port=8081,
        type="_grubstation._tcp.local.",
        properties={
            "mac": "aa:bb:cc:dd:ee:ff",
            "paired": "false",
            "address": "127.0.0.1",
        },
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=discovery_info,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "zeroconf_confirm"

    # Submit pairing step, mock async_pair to raise GrubStationApiConflictError
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        side_effect=GrubStationApiConflictError("Conflict: already paired"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "pin": "123456",
                "update_grub": True,
            },
        )
        assert result2["type"] == "form"
        assert result2["step_id"] == "zeroconf_confirm"
        assert result2["errors"] == {"base": "already_paired"}


async def test_options_flow_update_settings(hass: HomeAssistant) -> None:
    """Test that options flow updates config entry data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "webhook_id": "test_webhook_id",
            "api_key": "test_api_key",
            "ha_daemon_url": "https://ha.local:8123",
            "ha_grub_url": "http://10.0.0.1:8123",
            "update_grub": True,
            "turn_off_action": None,
        },
        unique_id="aa:bb:cc:dd:ee:ff",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "ha_daemon_url": "https://new-ha.local:8123",
            "ha_grub_url": "http://10.0.0.2:8123",
            "update_grub": False,
            "turn_off_action": "script.shutdown_pc",
        },
    )
    assert result2["type"] == "create_entry"
    assert entry.data["ha_daemon_url"] == "https://new-ha.local:8123"
    assert entry.data["ha_grub_url"] == "http://10.0.0.2:8123"
    assert entry.data["update_grub"] is False
    assert entry.data["turn_off_action"] == "script.shutdown_pc"


async def test_options_flow_clear_turn_off_action(hass: HomeAssistant) -> None:
    """Test that options flow can clear turn_off_action for non-daemonless entries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "webhook_id": "test_webhook_id",
            "api_key": "test_api_key",
            "ha_daemon_url": "https://ha.local:8123",
            "ha_grub_url": "http://10.0.0.1:8123",
            "update_grub": True,
            "turn_off_action": "script.shutdown_pc",
        },
        unique_id="aa:bb:cc:dd:ee:ff",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "ha_daemon_url": "https://ha.local:8123",
            "ha_grub_url": "http://10.0.0.1:8123",
            "update_grub": True,
            # turn_off_action omitted -> should be cleared to None
        },
    )
    assert result2["type"] == "create_entry"
    assert entry.data["turn_off_action"] is None


async def test_options_flow_daemonless_requires_turn_off_action(hass: HomeAssistant) -> None:
    """Test that options flow rejects empty turn_off_action for daemonless entries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "192.168.1.10",
            "port": 8081,
            "mac": "aa:bb:cc:dd:ee:ff",
            "webhook_id": "test_webhook_id",
            "api_key": "test_api_key",
            "ha_daemon_url": "https://ha.local:8123",
            "ha_grub_url": "http://10.0.0.1:8123",
            "update_grub": True,
            "turn_off_action": "script.shutdown_pc",
            "daemonless": True,
        },
        unique_id="aa:bb:cc:dd:ee:ff",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"

    # Try to submit without turn_off_action -> should show error
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "ha_daemon_url": "https://ha.local:8123",
            "ha_grub_url": "http://10.0.0.1:8123",
            "update_grub": True,
            # turn_off_action omitted
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "init"
    assert "turn_off_action" in result2["errors"]
