"""Helper functions for grubstation."""

from __future__ import annotations

import ipaddress


def is_ip_address(address: str) -> bool:
    """Check if address is a valid IP address."""
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return False
    else:
        return True


def format_display_name(host: str, hostname: str | None, fallback_prefix: str | None = None) -> str:
    """Format display name consistently and without redundancy."""
    if not hostname:
        return f"{fallback_prefix} ({host})" if fallback_prefix else host

    return f"{hostname} ({host})"
