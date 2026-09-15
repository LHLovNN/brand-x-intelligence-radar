from __future__ import annotations

import os
import socket


_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_IPV4_ONLY_ENABLED = False


def configure_outbound_network() -> None:
    """Prefer IPv4 when the local runtime has an unusable IPv6 route."""
    global _IPV4_ONLY_ENABLED

    value = os.getenv("BRAND_RADAR_FORCE_IPV4", "").strip().lower()
    if value not in {"1", "true", "yes", "on"} or _IPV4_ONLY_ENABLED:
        return

    def ipv4_getaddrinfo(
        host: str,
        port: int | str,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ):
        requested_family = socket.AF_INET if family in {0, socket.AF_UNSPEC} else family
        return _ORIGINAL_GETADDRINFO(host, port, requested_family, type, proto, flags)

    socket.getaddrinfo = ipv4_getaddrinfo
    _IPV4_ONLY_ENABLED = True
