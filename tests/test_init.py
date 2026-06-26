"""Tests for GrubStation integration setup and views."""

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grubstation.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_component import async_update_entity
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
            "ha_daemon_url": "http://127.0.0.1:8123",
            "ha_grub_url": "http://127.0.0.1:8123",
            "update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "test01",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_get_data",
            return_value={"status": "ok"},
        ),
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

        # Verify that the device is registered with the correct name
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
        assert device is not None
        assert device.name == "test01 (192.168.1.100)"

        # Verify that pre-boot view is registered and works
        client = await hass_client()

        # 1. Test GRUB pre-boot query view (invalid / unauthorized)
        resp = await client.get("/api/grubstation/AA:BB:CC:DD:EE:FF")
        assert resp.status == 401  # No token

        resp = await client.get("/api/grubstation/AA:BB:CC:DD:EE:FF?token=invalid_token")
        assert resp.status == 401  # Invalid token

        resp = await client.get("/api/grubstation/00:00:00:00:00:00?token=test_permanent_webhook")
        assert resp.status == 404  # Unknown MAC

        # 2. Test pre-boot query success with default choice
        resp = await client.get("/api/grubstation/AA:BB:CC:DD:EE:FF?token=test_permanent_webhook")
        assert resp.status == 200
        text = await resp.text()
        assert text == "default"

        # Set next boot override
        entry.runtime_data.next_boot = "Windows"

        # 3. Test pre-boot query success with override choice (which should consume it)
        resp = await client.get(
            "/api/grubstation/AA-BB-CC-DD-EE-FF?token=test_permanent_webhook"
        )  # also test dash format mac
        assert resp.status == 200
        text = await resp.text()
        assert text == "Windows"

        # Subsequent request should return "default" because the override was consumed
        resp = await client.get("/api/grubstation/aabbccddeeff?token=test_permanent_webhook")  # test no separator mac
        assert resp.status == 200
        text = await resp.text()
        assert text == "default"

        # 4. Test permanent Webhook update of boot options
        resp = await client.post(
            "/api/webhook/test_permanent_webhook",
            json={
                "boot_options": ["Linux", "Windows 11", "macOS"],
            },
        )
        assert resp.status == 200
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
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": "ok"}
        assert entry.runtime_data.coordinator.data == {
            "status": "stopped",
            "os": "FreeBSD",
        }

        # 6. Test unloading entry
        with patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_unpair",
            return_value={"status": "unpaired"},
        ):
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()

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
            "ha_daemon_url": "http://127.0.0.1:8123",
            "ha_grub_url": "http://127.0.0.1:8123",
            "update_grub": True,
            "boot_options": ["Linux"],
            "hostname": "wyse04",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_get_data",
            return_value={"status": "ok"},
        ),
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

        # Trigger update on both entities to pull the mocked status
        await async_update_entity(hass, binary_sensor_entity_id)
        await async_update_entity(hass, switch_entity_id)

        # 1. Daemon is "running": binary sensor should be "on" (connected) and switch should be "on"
        binary_sensor_state = hass.states.get(binary_sensor_entity_id)
        assert binary_sensor_state is not None
        assert binary_sensor_state.state == "on"

        switch_state = hass.states.get(switch_entity_id)
        assert switch_state is not None
        assert switch_state.state == "on"

    # 2. Daemon is "stopped": binary sensor should be "off" (disconnected) and switch should be "off"
    with (
        patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_get_data",
            return_value={"status": "ok"},
        ),
        patch(
            "custom_components.grubstation.api.GrubStationApiClient.async_get_status",
            return_value={
                "os": "Linux",
                "service_manager": "systemd",
                "status": "stopped",
                "version": "1.0.0",
            },
        ),
    ):
        await async_update_entity(hass, binary_sensor_entity_id)
        await async_update_entity(hass, switch_entity_id)

        binary_sensor_state = hass.states.get(binary_sensor_entity_id)
        assert binary_sensor_state is not None
        assert binary_sensor_state.state == "off"

        switch_state = hass.states.get(switch_entity_id)
        assert switch_state is not None
        assert switch_state.state == "off"
