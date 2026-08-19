"""SSRF rejection without a live site. DNS is only used for real hostnames."""

from __future__ import annotations

import ipaddress

import pytest

from shipcheck.ssrf import (
    UnsafeUrl,
    assert_redirect_target_safe,
    assert_url_allowed,
    hostname_is_blocked,
    ip_is_blocked,
    is_url_allowed,
    parse_ip,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "http://example.com",
        "ftp://example.com/",
        "ws://example.com/",
        "file:///etc/passwd",
        "file://localhost/etc/passwd",
        "javascript:alert(1)",
        "data:text/html,hi",
        "",
        "   ",
        "example.com",
        "//example.com/path",
        "https://",
        "https:///path",
    ],
)
def test_rejects_non_https_and_file(url: str) -> None:
    with pytest.raises(UnsafeUrl):
        assert_url_allowed(url, resolve=False)


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/",
        "https://localhost/foo",
        "https://LOCALHOST",
        "https://localhost.localdomain/",
        "https://foo.localhost/",
        "https://host.docker.internal/",
        "https://metadata.google.internal/",
        "https://metadata.google.com/",
        "https://something.internal/path",
        "https://printer.lan/",
        "https://nas.home/",
        "https://box.corp/admin",
    ],
)
def test_rejects_blocked_hostnames(url: str) -> None:
    with pytest.raises(UnsafeUrl):
        assert_url_allowed(url, resolve=False)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://127.0.0.1:8443/secret",
        "https://127.1.2.3/",
        "https://0.0.0.0/",
        "https://10.0.0.1/",
        "https://10.255.255.254/x",
        "https://172.16.0.1/",
        "https://172.31.255.1/",
        "https://192.168.0.1/",
        "https://192.168.1.50:443/",
        "https://169.254.1.1/",
        "https://169.254.169.254/",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/",
        "https://[::1]:443/",
        "https://[fc00::1]/",
        "https://[fe80::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://[::ffff:192.168.0.1]/",
        "https://[::ffff:169.254.169.254]/",
        "https://100.64.0.1/",
        "https://100.127.0.1/",
    ],
)
def test_rejects_private_and_metadata_ips(url: str) -> None:
    with pytest.raises(UnsafeUrl):
        assert_url_allowed(url, resolve=True)


def test_rejects_decimal_loopback() -> None:
    # 2130706433 == 127.0.0.1
    with pytest.raises(UnsafeUrl):
        assert_url_allowed("https://2130706433/", resolve=False)


def test_rejects_embedded_credentials() -> None:
    with pytest.raises(UnsafeUrl):
        assert_url_allowed("https://user:pass@example.com/", resolve=False)


def test_ip_helpers() -> None:
    assert ip_is_blocked(ipaddress.ip_address("10.1.2.3"))
    assert ip_is_blocked(ipaddress.ip_address("172.16.0.9"))
    assert ip_is_blocked(ipaddress.ip_address("192.168.10.2"))
    assert ip_is_blocked(ipaddress.ip_address("169.254.169.254"))
    assert ip_is_blocked(ipaddress.ip_address("127.0.0.1"))
    assert ip_is_blocked(ipaddress.ip_address("::1"))
    assert ip_is_blocked(ipaddress.ip_address("::ffff:10.0.0.1"))
    assert not ip_is_blocked(ipaddress.ip_address("8.8.8.8"))
    assert not ip_is_blocked(ipaddress.ip_address("1.1.1.1"))
    assert parse_ip("127.0.0.1") == ipaddress.ip_address("127.0.0.1")
    assert hostname_is_blocked("localhost")
    assert hostname_is_blocked("metadata.google.internal")


def test_redirect_to_private_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # urljoin of a relative Location onto a public URL still ends at loopback.
    with pytest.raises(UnsafeUrl):
        assert_redirect_target_safe("https://example.com/app", "https://127.0.0.1/admin")
    with pytest.raises(UnsafeUrl):
        assert_redirect_target_safe("https://example.com/app", "https://169.254.169.254/")
    with pytest.raises(UnsafeUrl):
        assert_redirect_target_safe("https://example.com/app", "http://example.com/downgrade")
    with pytest.raises(UnsafeUrl):
        assert_redirect_target_safe("https://example.com/app", "file:///etc/passwd")


def test_public_https_structural() -> None:
    assert is_url_allowed("https://example.com/", resolve=False)
    assert is_url_allowed("https://example.com/foo?x=1", resolve=False)
    assert is_url_allowed("https://preview-abc.vercel.app/", resolve=False)


def test_example_com_resolves_public() -> None:
    # Real DNS, no HTTP. Fails the suite if example.com ever pointed at RFC1918.
    assert_url_allowed("https://example.com/", resolve=True)
