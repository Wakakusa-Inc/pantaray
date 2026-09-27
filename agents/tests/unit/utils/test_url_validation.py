from __future__ import annotations

import pytest

from pantaray_agents.utils.url_validation import parse_network_url

PROXY_URL_ENV = "TEST_PROXY_URL"


@pytest.mark.parametrize(
    ("raw_url", "expected_host", "expected_port"),
    [
        ("http://localhost:8000", "localhost", 8000),
        ("http://127.0.0.1:8000", "127.0.0.1", 8000),
        ("http://127.255.255.254:8000", "127.255.255.254", 8000),
        ("http://[::1]:8000", "::1", 8000),
        ("http://deps.127.0.0.1:8006", "deps.127.0.0.1", 8006),
        ("http://sub.deps.127.0.0.1", "sub.deps.127.0.0.1", 80),
    ],
)
def test_parse_network_url_accepts_loopback_http(
    raw_url: str,
    expected_host: str,
    expected_port: int,
) -> None:
    parsed = parse_network_url(raw_url, env_name=PROXY_URL_ENV, allow_path=False)

    assert parsed.scheme == "http"
    assert parsed.host == expected_host
    assert parsed.port == expected_port


def test_parse_network_url_accepts_non_loopback_https() -> None:
    parsed = parse_network_url(
        "https://proxy.example.com",
        env_name=PROXY_URL_ENV,
        allow_path=False,
    )

    assert parsed.scheme == "https"
    assert parsed.host == "proxy.example.com"
    assert parsed.port == 443


@pytest.mark.parametrize(
    "raw_url",
    [
        "http://proxy.example.com",
        "http://192.0.2.1",
        "http://127.0.0.1.evil.com",
        "http://evil.example.com",
    ],
)
def test_parse_network_url_rejects_non_loopback_http(raw_url: str) -> None:
    with pytest.raises(
        ValueError,
        match=f"{PROXY_URL_ENV} must use https for non-loopback hosts",
    ):
        parse_network_url(raw_url, env_name=PROXY_URL_ENV, allow_path=False)
