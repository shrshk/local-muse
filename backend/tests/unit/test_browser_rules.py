import pytest

from muse.browser.netguard import BlockedURL, HostGuard, domain_of, is_global_address, validate_url


@pytest.mark.parametrize("url", ["https://example.com", "http://example.com/a?b=c"])
def test_http_urls_are_accepted(url: str):
    assert validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "chrome://settings",
        "data:text/html,<h1>x</h1>",
        "ftp://example.com",
        "https://",
        "example.com",
    ],
)
def test_other_schemes_and_hostless_urls_are_blocked(url: str):
    with pytest.raises(BlockedURL):
        validate_url(url)


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.215.14", True),
        ("2606:2800:21f:cb07:6820:80da:af6b:8b2c", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("172.18.0.3", False),
        ("192.168.65.254", False),
        ("169.254.169.254", False),
        ("::1", False),
        ("fd00::1", False),
        ("0.0.0.0", False),
    ],
)
def test_only_globally_routable_addresses_count_as_public(address: str, public: bool):
    assert is_global_address(address) is public


async def test_literal_private_hosts_and_unresolvable_names_are_refused():
    guard = HostGuard()
    assert not await guard.allows("127.0.0.1")
    assert not await guard.allows("169.254.169.254")
    assert not await guard.allows("definitely-not-a-real-host.invalid")


def test_domain_of_lowercases_the_host():
    assert domain_of("https://Docs.Python.org/3/") == "docs.python.org"
