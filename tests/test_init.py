"""Tests for GrubStation integration setup and views."""

from http import HTTPStatus
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.grubstation.const import DOMAIN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component


async def test_setup_unload_and_webhook(hass: HomeAssistant, hass_client) -> None:
    """Test setting up and unloading the integration, and receiving webhook updates."""
    # Setup HTTP and webhook components first
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "192.168.1.100",
            "port": 8081,
            "mac": "AA:BB:CC:DD:EE:FF",
            "webhook_id": "test_permanent_webhook",
            "api_key": "test_api_key",
            "daemon_url": "http://127.0.0.1:8123",
            "grub_url": "http://127.0.0.1:8123",
            "update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "test01",
            "daemon_token": "test_daemon_token",
        },
    )
    entry.add_to_hass(hass)

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
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Verify that the device is registered with the correct name and connections
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
        assert device is not None
        assert device.name == "test01"
        assert device.connections == {(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")}

        # Verify that pre-boot view is registered and works
        client = await hass_client()

        # 1. Test GRUB pre-boot query view (no token is allowed, invalid token returns 401)
        resp = await client.get("/api/grubstation/AA:BB:CC:DD:EE:FF")
        assert resp.status == HTTPStatus.OK
        text = await resp.text()
        assert text == "default"

        resp = await client.get("/api/grubstation/AA:BB:CC:DD:EE:FF?token=invalid_token")
        assert resp.status == HTTPStatus.UNAUTHORIZED  # Invalid token

        resp = await client.get("/api/grubstation/00:00:00:00:00:00?token=test_permanent_webhook")
        assert resp.status == HTTPStatus.NOT_FOUND  # Unknown MAC

        # 2. Test pre-boot query success with default choice and valid token
        resp = await client.get("/api/grubstation/AA:BB:CC:DD:EE:FF?token=test_permanent_webhook")
        assert resp.status == HTTPStatus.OK
        text = await resp.text()
        assert text == "default"

        # Set next boot override
        entry.runtime_data.next_boot = "Windows"

        # Query without token should return "Windows" but NOT consume it
        resp = await client.get("/api/grubstation/AA:BB:CC:DD:EE:FF")
        assert resp.status == HTTPStatus.OK
        text = await resp.text()
        assert text == "Windows"

        # 3. Test pre-boot query success with override choice and valid token (which should consume it)
        resp = await client.get(
            "/api/grubstation/AA-BB-CC-DD-EE-FF?token=test_permanent_webhook"
        )  # also test dash format mac
        assert resp.status == HTTPStatus.OK
        text = await resp.text()
        assert text == "Windows"

        # Subsequent request should return "default" because the override was consumed
        resp = await client.get("/api/grubstation/aabbccddeeff?token=test_permanent_webhook")  # test no separator mac
        assert resp.status == HTTPStatus.OK
        text = await resp.text()
        assert text == "default"

        # 4. Test permanent Webhook update of boot options
        resp = await client.post(
            "/api/webhook/test_permanent_webhook",
            json={
                "boot_options": ["Linux", "Windows 11", "macOS"],
            },
        )
        assert resp.status == HTTPStatus.OK
        data = await resp.json()
        assert data == {"status": "ok"}
        assert entry.data["boot_options"] == ["Linux", "Windows 11", "macOS"]

        # 5. Test permanent Webhook update of status/coordinator data
        resp = await client.post(
            "/api/webhook/test_permanent_webhook",
            json={
                "status": "stopped",
                "os": "FreeBSD",
            },
        )
        assert resp.status == HTTPStatus.OK
        data = await resp.json()
        assert data == {"status": "ok"}
        assert entry.runtime_data.coordinator.data == {
            "status": "stopped",
            "os": "FreeBSD",
            "service_manager": "systemd",
            "version": "1.0.0",
        }

        # 6. Test unloading entry
        with patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_unpair",
            return_value={"status": "unpaired"},
        ) as mock_unpair:
            result = await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()
            assert result["require_restart"] is False
            mock_unpair.assert_called_once_with(daemon_token="test_daemon_token")

        # The webhook should now be unregistered
        assert "test_permanent_webhook" not in hass.data.get("webhook", {}).get("handlers", {})


async def test_binary_sensor_and_switch_states(hass: HomeAssistant) -> None:
    """Test that binary sensor and switch reflect the daemon status."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "AA:BB:CC:DD:EE:FF",
            "webhook_id": "test_permanent_webhook",
            "api_key": "test_api_key",
            "daemon_url": "http://127.0.0.1:8123",
            "grub_url": "http://127.0.0.1:8123",
            "update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "wyse04",
            "daemon_token": "test_daemon_token",
        },
    )
    entry.add_to_hass(hass)

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
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Retrieve entity registry to look up entities dynamically
        entity_registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        binary_sensor_entity_id = next(e.entity_id for e in entities if e.domain == "binary_sensor")
        switch_entity_id = next(e.entity_id for e in entities if e.domain == "switch")
        select_entity_id = next(e.entity_id for e in entities if e.domain == "select")

        # Verify initial state after a successful pair/setup is "on"
        assert hass.states.get(binary_sensor_entity_id).state == "on"
        assert hass.states.get(switch_entity_id).state == "on"

        # Verify the select entity is enabled and defaults to "default"
        assert hass.states.get(select_entity_id).state == "default"

        # Trigger update on both entities to pull the mocked status
        await entry.runtime_data.coordinator.async_refresh()

        # 1. Daemon is "running": binary sensor should be "on" (connected) and switch should be "on"
        binary_sensor_state = hass.states.get(binary_sensor_entity_id)
        assert binary_sensor_state is not None
        assert binary_sensor_state.state == "on"

        switch_state = hass.states.get(switch_entity_id)
        assert switch_state is not None
        assert switch_state.state == "on"

    # 2. Daemon is unreachable: binary sensor should be "off" (disconnected) and switch should be "off"
    with (
        patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_get_status",
            side_effect=Exception("Connection failed"),
        ),
    ):
        await entry.runtime_data.coordinator.async_refresh()

        binary_sensor_state = hass.states.get(binary_sensor_entity_id)
        assert binary_sensor_state is not None
        assert binary_sensor_state.state == "off"

        switch_state = hass.states.get(switch_entity_id)
        assert switch_state is not None
        assert switch_state.state == "off"


async def test_switch_turn_off_default(hass: HomeAssistant) -> None:
    """Test switch turn off calls default API shutdown when no custom action."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "AA:BB:CC:DD:EE:FF",
            "webhook_id": "test_permanent_webhook",
            "api_key": "test_api_key",
            "daemon_url": "http://127.0.0.1:8123",
            "grub_url": "http://127.0.0.1:8123",
            "run_update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "wyse04",
            "daemon_token": "test_daemon_token",
        },
    )
    entry.add_to_hass(hass)

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
            "custom_components.grubstation.api.GrubStationApiClient.async_shutdown",
            return_value={"status": "ok"},
        ) as mock_shutdown,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Retrieve switch entity
        entity_registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        switch_entity_id = next(e.entity_id for e in entities if e.domain == "switch")

        # Turn off the switch
        await hass.services.async_call("switch", "turn_off", {"entity_id": switch_entity_id}, blocking=True)
        mock_shutdown.assert_called_once_with(daemon_token="test_daemon_token")


async def test_switch_turn_on(hass: HomeAssistant) -> None:
    """Test switch turn on."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "AA:BB:CC:DD:EE:FF",
            "webhook_id": "test_permanent_webhook",
            "api_key": "test_api_key",
            "daemon_url": "http://127.0.0.1:8123",
            "grub_url": "http://127.0.0.1:8123",
            "run_update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "wyse04",
            "daemon_token": "test_daemon_token",
        },
    )
    entry.add_to_hass(hass)

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
        patch("custom_components.grubstation.switch.wakeonlan.wake") as mock_wake,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Retrieve switch entity
        entity_registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        switch_entity_id = next(e.entity_id for e in entities if e.domain == "switch")

        # Turn on the switch
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch_entity_id}, blocking=True)
        mock_wake.assert_called_once_with("AA:BB:CC:DD:EE:FF", host="255.255.255.255", port=9)


async def test_select_restore_state(hass: HomeAssistant) -> None:
    """Test that next boot option select restores its state from last state."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    # Mock the restore state helper with "Linux"
    mock_restore_cache(hass, [State("select.wyse04_next_boot_option", "Linux")])

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "AA:BB:CC:DD:EE:FF",
            "webhook_id": "test_permanent_webhook",
            "api_key": "test_api_key",
            "daemon_url": "http://127.0.0.1:8123",
            "grub_url": "http://127.0.0.1:8123",
            "run_update_grub": True,
            "boot_options": ["Linux", "Windows"],
            "hostname": "wyse04",
            "daemon_token": "test_daemon_token",
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.grubstation.api.GrubStationApiClient.async_get_status",
        return_value={
            "os": "Linux",
            "service_manager": "systemd",
            "status": "running",
            "version": "1.0.0",
        },
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Check that runtime_data.next_boot was restored to "Linux"
        assert entry.runtime_data.next_boot == "Linux"


async def test_daemonless_button_instead_of_switch(hass: HomeAssistant) -> None:
    """Test that daemonless entries setup a button instead of a switch, and pressing it wakes the host."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "AA:BB:CC:DD:EE:FF",
            "webhook_id": "test_permanent_webhook",
            "api_key": "test_api_key",
            "daemon_url": "http://127.0.0.1:8123",
            "grub_url": "http://127.0.0.1:8123",
            "run_update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "wyse04",
            "daemonless": True,
        },
    )
    entry.add_to_hass(hass)

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
        patch("custom_components.grubstation.button.wakeonlan.wake") as mock_wake,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

        # There should be no switch entity
        switch_entities = [e for e in entities if e.domain == "switch"]
        assert len(switch_entities) == 0

        # There should be a button entity
        button_entity_id = next(e.entity_id for e in entities if e.domain == "button")
        assert button_entity_id is not None

        # Press the button
        await hass.services.async_call("button", "press", {"entity_id": button_entity_id}, blocking=True)
        mock_wake.assert_called_once_with("AA:BB:CC:DD:EE:FF", host="255.255.255.255", port=9)


async def test_daemonless_button_custom_wol_parameters(hass: HomeAssistant) -> None:
    """Test that a daemonless entry button correctly uses custom WoL parameters."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "AA:BB:CC:DD:EE:FF",
            "webhook_id": "test_permanent_webhook",
            "api_key": "test_api_key",
            "daemon_url": "http://127.0.0.1:8123",
            "grub_url": "http://127.0.0.1:8123",
            "run_update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "wyse04",
            "daemonless": True,
            "wol_broadcast": "192.168.1.255",
            "wol_port": 7,
        },
    )
    entry.add_to_hass(hass)

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
        patch("custom_components.grubstation.button.wakeonlan.wake") as mock_wake,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

        # There should be a button entity
        button_entity_id = next(e.entity_id for e in entities if e.domain == "button")
        assert button_entity_id is not None

        # Press the button
        await hass.services.async_call("button", "press", {"entity_id": button_entity_id}, blocking=True)
        mock_wake.assert_called_once_with("AA:BB:CC:DD:EE:FF", host="192.168.1.255", port=7)


async def test_switch_daemonless_custom_action(hass: HomeAssistant, hass_client) -> None:
    """Test switch turn off calls custom Home Assistant service call in daemonless mode."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "webhook", {})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "ip_address": "127.0.0.1",
            "port": 8081,
            "mac": "AA:BB:CC:DD:EE:FF",
            "webhook_id": "test_permanent_webhook",
            "api_key": "test_api_key",
            "daemon_url": "http://127.0.0.1:8123",
            "grub_url": "http://127.0.0.1:8123",
            "run_update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "wyse04",
            "daemonless": True,
            "turn_off_action": "script.my_custom_shutdown",
        },
    )
    entry.add_to_hass(hass)

    # Register a mock service for script.my_custom_shutdown
    mock_service_calls = []

    async def mock_service_handler(call) -> None:
        mock_service_calls.append(call)

    hass.services.async_register("script", "my_custom_shutdown", mock_service_handler)

    with patch("custom_components.grubstation.switch.wakeonlan.wake") as mock_wake:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Retrieve switch entity
        entity_registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        switch_entity_id = next(e.entity_id for e in entities if e.domain == "switch")

        # Initial state should be off
        state = hass.states.get(switch_entity_id)
        assert state.state == "off"

        # Turn on the switch
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch_entity_id}, blocking=True)
        mock_wake.assert_called_once_with("AA:BB:CC:DD:EE:FF", host="255.255.255.255", port=9)

        # State should now be on (optimistic status update)
        state = hass.states.get(switch_entity_id)
        assert state.state == "on"

        # Turn off the switch
        await hass.services.async_call("switch", "turn_off", {"entity_id": switch_entity_id}, blocking=True)
        assert len(mock_service_calls) == 1

        # State should now be off
        state = hass.states.get(switch_entity_id)
        assert state.state == "off"

        # Simulate host booting (GET boot query to API)
        client = await hass_client()
        resp = await client.get("/api/grubstation/AA:BB:CC:DD:EE:FF")
        assert resp.status == HTTPStatus.OK

        # State should now be on because boot query was received
        state = hass.states.get(switch_entity_id)
        assert state.state == "on"
