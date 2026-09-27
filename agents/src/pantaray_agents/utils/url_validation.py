from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from urllib.parse import urlparse

ALLOWED_NETWORK_URL_SCHEMES = frozenset({"http", "https"})
DEFAULT_HTTP_PORT = 80
DEFAULT_HTTPS_PORT = 443
IPV6_LOOPBACK_ADDRESS = IPv6Address("::1")


@dataclass(frozen=True, slots=True)
class ValidatedNetworkUrl:
    url: str
    scheme: str
    host: str
    port: int
    path: str


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    # The local dependency proxy reserves *.127.0.0.1 for Host-based routing.
    # Its numeric top-level label cannot resolve through public DNS.
    if host.endswith(".127.0.0.1"):
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return (isinstance(address, IPv4Address) and address.is_loopback) or (
        address == IPV6_LOOPBACK_ADDRESS
    )


def parse_network_url(
    raw_url: str,
    *,
    env_name: str,
    allow_path: bool,
) -> ValidatedNetworkUrl:
    value = raw_url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ALLOWED_NETWORK_URL_SCHEMES:
        raise ValueError(f"{env_name} must use http or https: {value!r}")
    host = parsed.hostname
    if host is None or not host.strip():
        raise ValueError(f"{env_name} must include a hostname: {value!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{env_name} must not embed credentials")
    if parsed.scheme == "http" and not _is_loopback_host(host):
        raise ValueError(f"{env_name} must use https for non-loopback hosts: {value!r}")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError(
            f"{env_name} must not include params, query, or fragment: {value!r}"
        )
    if not allow_path and parsed.path not in {"", "/"}:
        raise ValueError(f"{env_name} must be an origin-only URL: {value!r}")
    port = parsed.port
    if port is None:
        port = DEFAULT_HTTPS_PORT if parsed.scheme == "https" else DEFAULT_HTTP_PORT
    return ValidatedNetworkUrl(
        url=value,
        scheme=parsed.scheme,
        host=host,
        port=port,
        path=parsed.path,
    )
