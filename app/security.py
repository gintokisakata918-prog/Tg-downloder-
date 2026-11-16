"""URL validation helpers.

The API accepts arbitrary links, so before handing one to an engine we make
sure it speaks HTTP(S) and does not point at the local network. This is a
best-effort guard: DNS can change between the check and the actual request,
and some engines follow redirects on their own.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}


class UnsafeURLError(ValueError):
    """Raised when a URL is malformed or resolves to a forbidden address."""


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def normalize_url(raw: str) -> str:
    """Validate the URL shape and return a normalized string."""
    url = (raw or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Sirf http:// ya https:// links chalenge.")
    if not parsed.hostname:
        raise UnsafeURLError("Link mein hostname nahi mila.")
    if len(url) > 2048:
        raise UnsafeURLError("Link bahut lamba hai.")
    return parsed.geturl()


async def ensure_public_url(raw: str, *, allow_private: bool = False) -> str:
    """Validate a URL and (by default) reject private network targets."""
    url = normalize_url(raw)
    if allow_private:
        return url

    hostname = urlparse(url).hostname or ""
    if hostname.lower() in BLOCKED_HOSTNAMES:
        raise UnsafeURLError("Yeh host allowed nahi hai.")

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError("Host resolve nahi ho paya.") from exc

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_forbidden_ip(ip):
            raise UnsafeURLError("Private / local network links allowed nahi hain.")

    return url
