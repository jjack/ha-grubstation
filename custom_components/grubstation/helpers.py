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

    # If host is already an IP address, return "hostname (IP)"
    if is_ip_address(host):
        return f"{hostname} ({host})"

    # If host is a hostname/FQDN, check if the base names are redundant
    host_prefix = host.split(".", maxsplit=1)[0].lower()
    hostname_prefix = hostname.split(".", maxsplit=1)[0].lower()

    if host_prefix == hostname_prefix:
        # Redundant, return the host FQDN
        return host

    return f"{hostname} ({host})"
