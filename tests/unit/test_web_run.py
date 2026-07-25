from __future__ import annotations

from unittest.mock import Mock

import pytest

from swipe_dating.web import run as web_run
from swipe_dating.web.run import normalize_loopback_host, normalize_loopback_origin


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("localhost", "localhost"),
        ("127.0.0.0", "127.0.0.0"),
        ("127.0.0.1", "127.0.0.1"),
        ("127.42.3.9", "127.42.3.9"),
        ("127.255.255.255", "127.255.255.255"),
        ("::1", "::1"),
        ("0:0:0:0:0:0:0:1", "::1"),
    ),
)
def test_normalize_loopback_host_accepts_only_local_bind_targets(
    value: str,
    expected: str,
) -> None:
    assert normalize_loopback_host(value) == expected


@pytest.mark.parametrize(
    "value",
    (
        "",
        " ",
        " localhost",
        "localhost ",
        "0.0.0.0",  # noqa: S104 - rejection case
        "::",
        "192.0.2.1",
        "8.8.8.8",
        "example.com",
        "localhost.example",
        "127.0.0.1:8080",
        "[::1]",
        "127.0.0.999",
    ),
)
def test_normalize_loopback_host_rejects_non_loopback_or_malformed_values(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="loopback"):
        normalize_loopback_host(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("http://localhost", "http://localhost"),
        ("http://LOCALHOST/", "http://localhost"),
        ("https://127.0.0.1:8443/", "https://127.0.0.1:8443"),
        ("http://127.42.3.9:8080", "http://127.42.3.9:8080"),
        ("http://[::1]", "http://[::1]"),
        (
            "https://[0:0:0:0:0:0:0:1]:4443/",
            "https://[::1]:4443",
        ),
    ),
)
def test_normalize_loopback_origin_accepts_http_origins_and_removes_root_slash(
    value: str,
    expected: str,
) -> None:
    assert normalize_loopback_origin(value) == expected


@pytest.mark.parametrize(
    "value",
    (
        "",
        " ",
        "\x00http://localhost",
        "http://localhost ",
        "localhost:8080",
        "ftp://localhost",
        "file:///tmp/app",
        "http://user@localhost",
        "http://user:password@localhost",
        "http://0.0.0.0:8080",
        "http://[::]:8080",
        "http://192.0.2.1",
        "https://example.com",
        "http://localhost?mode=test",
        "http://localhost#main",
        "http://localhost/app",
        "http://localhost//",
        "http:///",
        "http://localhost:",
        "http://localhost:not-a-port",
        "http://localhost:65536",
    ),
)
def test_normalize_loopback_origin_rejects_unsafe_or_non_origin_values(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="loopback"):
        normalize_loopback_origin(value)


def test_main_rejects_non_loopback_host_before_browser_or_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_timer = Mock()
    uvicorn_run = Mock()
    monkeypatch.setenv("HOST", "0.0.0.0")  # noqa: S104 - rejection case
    monkeypatch.setattr(web_run.threading, "Timer", browser_timer)
    monkeypatch.setattr(web_run.uvicorn, "run", uvicorn_run)

    with pytest.raises(ValueError, match="loopback"):
        web_run.main()

    browser_timer.assert_not_called()
    uvicorn_run.assert_not_called()


def test_main_keeps_the_default_ipv4_loopback_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uvicorn_run = Mock()
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("SWIPE_WEB_OPEN_BROWSER", "0")
    monkeypatch.setattr(web_run.uvicorn, "run", uvicorn_run)

    web_run.main()

    uvicorn_run.assert_called_once_with(
        "swipe_dating.web.app:app",
        host="127.0.0.1",
        port=8080,
        reload=False,
    )
