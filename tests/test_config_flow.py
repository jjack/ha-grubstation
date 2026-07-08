"""Tests for GrubStation config flow."""

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grubstation.api import GrubStationApiConflictError, GrubStationApiInvalidPinError
from custom_components.grubstation.const import CONF_ADVANCED_OPTIONS, DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.setup import async_setup_component


async def test_config_flow(hass: HomeAssistant) -> None:
    """Test the config flow user and pairing steps."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Select agent type
    result_type = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "setup_type": "agent",
        },
    )
    assert result_type["type"] == "form"
    assert result_type["step_id"] == "agent_config"

    # Submit pairing step, which generates credentials and calls pairing API
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        return_value={
            "paired": True,
            "mac": "aa:bb:cc:dd:ee:ff",
        },
    ) as mock_pair:
        result2 = await hass.config_entries.flow.async_configure(
            result_type["flow_id"],
            {
                "ip_address": "127.0.0.1",
                "pin": "123456",
                CONF_ADVANCED_OPTIONS: {
                    "port": 8081,
                    "update_grub": False,
                },
            },
        )
        assert result2["type"] == "create_entry"
        assert result2["title"] == "GrubStation (127.0.0.1)"
        assert result2["data"]["update_grub"] is False
        assert result2["data"]["mac"] == "aa:bb:cc:dd:ee:ff"
        assert mock_pair.call_args.kwargs["pin"] == "123456"
        assert mock_pair.call_args.kwargs["update_grub"] is False


async def test_config_flow_invalid_ip(hass: HomeAssistant) -> None:
    """Test that config flow rejects a host that is not an IP address."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Select agent type
    result_type = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "setup_type": "agent",
        },
    )
    assert result_type["type"] == "form"
    assert result_type["step_id"] == "agent_config"

    # Submit user step with a non-IP host address
    result2 = await hass.config_entries.flow.async_configure(
        result_type["flow_id"],
        {
            "ip_address": "grubstation.local",
            "pin": "123456",
            CONF_ADVANCED_OPTIONS: {
                "port": 8081,
            },
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "agent_config"
    assert result2["errors"] == {"ip_address": "invalid_ip"}


async def test_config_flow_pin_required_and_invalid_and_success(
    hass: HomeAssistant,
) -> None:
    """Test config flow when PIN is invalid, then correct."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Select agent type
    result_type = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "setup_type": "agent",
        },
    )
    assert result_type["type"] == "form"
    assert result_type["step_id"] == "agent_config"

    # 1. Submit invalid PIN. Mock it to raise GrubStationApiInvalidPinError
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        side_effect=GrubStationApiInvalidPinError("Invalid PIN entered"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result_type["flow_id"],
            {
                "ip_address": "127.0.0.1",
                "pin": "wrong_pin",
                CONF_ADVANCED_OPTIONS: {
                    "port": 8081,
                },
            },
        )
    assert result2["type"] == "form"
    assert result2["step_id"] == "agent_config"
    assert result2["errors"] == {"base": "invalid_pin"}

    # 2. Submit valid PIN. Mock it to return success response
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        return_value={
            "paired": True,
            "mac": "aa:bb:cc:dd:ee:ff",
            "boot_options": ["linux"],
        },
    ) as mock_pair:
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                "ip_address": "127.0.0.1",
                "pin": "123456",
                CONF_ADVANCED_OPTIONS: {
                    "port": 8081,
                },
            },
        )
    assert result3["type"] == "create_entry"
    assert result3["title"] == "GrubStation (127.0.0.1)"
    assert result3["data"]["update_grub"] is True
    assert result3["data"]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert mock_pair.call_args.kwargs["pin"] == "123456"
    assert mock_pair.call_args.kwargs["update_grub"] is True


async def test_config_flow_pin_connection_error(hass: HomeAssistant) -> None:
    """Test config flow when agent config encounters a connection error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    # Select agent type
    result_type = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "setup_type": "agent",
        },
    )
    assert result_type["type"] == "form"
    assert result_type["step_id"] == "agent_config"

    # Submit PIN resulting in connection error
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        side_effect=Exception("Connection lost"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result_type["flow_id"],
            {
                "ip_address": "127.0.0.1",
                "pin": "123456",
                CONF_ADVANCED_OPTIONS: {
                    "port": 8081,
                },
            },
        )
    assert result2["type"] == "form"
    assert result2["step_id"] == "agent_config"
    assert result2["errors"] == {"base": "connection"}


async def test_config_flow_daemonless(hass: HomeAssistant, hass_client) -> None:
    # Setup HTTP and webhook components first so hass.http is not None
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # Select daemonless type
    result_type = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "setup_type": "daemonless",
        },
    )
    assert result_type["type"] == "form"
    assert result_type["step_id"] == "daemonless_config"

    # Fill host info, mac, daemonless=True
    result2 = await hass.config_entries.flow.async_configure(
        result_type["flow_id"],
        {
            "ip_address": "192.168.1.10",
            "mac": "aa:bb:cc:dd:ee:ff",
            CONF_ADVANCED_OPTIONS: {
                "update_grub": False,
            },
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "daemonless_onboarding"
    assert '"update_grub": false' in result2["description_placeholders"]["pairing_command"]

    # Submit without running the CLI command/callback first -> should show error
    result3 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {},
    )
    assert result3["type"] == "form"
    assert result3["step_id"] == "daemonless_onboarding"
    assert result3["errors"] == {"base": "waiting_for_device_callback"}

    # Simulate the remote machine sending the pairing webhook callback
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
    assert result4["data"]["update_grub"] is False
    assert result4["data"]["boot_options"] == [
        "Ubuntu",
        "Windows Boot Manager",
    ]


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
    assert flow.context["title_placeholders"] == {"name": "grubstation.local"}

    # Submit pairing step, which generates credentials and calls pairing API
    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_pair",
        return_value={"paired": True},
    ) as mock_pair:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "pin": "123456",
                CONF_ADVANCED_OPTIONS: {
                    "ha_daemon_url": "https://my-ha.duckdns.org:8123",
                    "ha_grub_url": "http://10.15.0.5:8123",
                    "update_grub": True,
                },
            },
        )
        assert result2["type"] == "create_entry"
        assert result2["title"] == "grubstation.local"
        assert result2["data"]["mac"] == "aa:bb:cc:dd:ee:ff"
        assert result2["data"]["ip_address"] == "127.0.0.1"
        assert result2["data"]["ha_daemon_url"] == "https://my-ha.duckdns.org:8123"
        assert result2["data"]["ha_grub_url"] == "http://10.15.0.5:8123"
        assert result2["data"]["update_grub"] is True
        assert mock_pair.call_args.kwargs["pin"] == "123456"
        assert mock_pair.call_args.kwargs["update_grub"] is True


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
                CONF_ADVANCED_OPTIONS: {
                    "update_grub": True,
                },
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
