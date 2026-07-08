"""Tests for GrubStation helper functions."""

from custom_components.grubstation.helpers import format_display_name, is_ip_address


def test_is_ip_address() -> None:
    """Test is_ip_address function."""
    assert is_ip_address("127.0.0.1") is True
    assert is_ip_address("192.168.1.100") is True
    assert is_ip_address("2001:db8::1") is True
    assert is_ip_address("grubstation.local") is False
    assert is_ip_address("localhost") is False


def test_format_display_name() -> None:
    """Test format_display_name function."""
    # 1. No hostname, with fallback prefix
    assert format_display_name("192.168.1.100", None, "GrubStation") == "GrubStation (192.168.1.100)"
    assert format_display_name("192.168.1.100", None) == "192.168.1.100"

    # 2. Host is an IP address
    assert format_display_name("192.168.1.100", "livingroom-pc.local") == "livingroom-pc.local"
