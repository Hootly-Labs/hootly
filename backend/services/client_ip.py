"""Shared helper to extract the real client IP behind trusted proxies."""
import ipaddress
import os

from fastapi import Request

# Comma-separated list of trusted reverse-proxy IPs or CIDR ranges
# (e.g. "127.0.0.1,100.64.0.0/10").  When the direct connection comes from
# one of these, X-Forwarded-For is trusted to extract the real client IP.
_TRUSTED_PROXY_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
for _entry in os.getenv("TRUSTED_PROXY_IPS", "").split(","):
    _entry = _entry.strip()
    if _entry:
        try:
            _TRUSTED_PROXY_NETWORKS.append(ipaddress.ip_network(_entry, strict=False))
        except ValueError:
            pass


def _is_trusted_proxy(ip_str: str) -> bool:
    if not _TRUSTED_PROXY_NETWORKS:
        return False
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in _TRUSTED_PROXY_NETWORKS)


def get_client_ip(request: Request) -> str:
    """Return the real client IP, honouring X-Forwarded-For only when the
    direct connection comes from a known trusted proxy."""
    raw = request.client.host if request.client else None
    if raw and _is_trusted_proxy(raw):
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    return raw or "unknown"
