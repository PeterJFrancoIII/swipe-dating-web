"""Local launcher for the synthetic bot-control web app."""

from __future__ import annotations

import os
import threading
import webbrowser
from ipaddress import IPv4Address, IPv6Address, ip_address
from urllib.parse import urlsplit

import uvicorn


def normalize_loopback_host(value: str) -> str:
    """Return a canonical local-only bind host or reject it."""
    if not value or value != value.strip():
        raise ValueError("host must be a loopback address or localhost")
    if value.lower() == "localhost":
        return "localhost"

    try:
        address = ip_address(value)
    except ValueError as error:
        raise ValueError("host must be a loopback address or localhost") from error

    if isinstance(address, IPv4Address):
        if not address.is_loopback:
            raise ValueError("host must be a loopback address or localhost")
    elif not isinstance(address, IPv6Address) or address != IPv6Address("::1"):
        raise ValueError("host must be a loopback address or localhost")
    return str(address)


def normalize_loopback_origin(value: str) -> str:
    """Return a canonical HTTP(S) loopback origin without a trailing slash."""
    error_message = "URL must be an HTTP(S) loopback origin"
    if (
        not value
        or not value.isprintable()
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise ValueError(error_message)

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError(error_message) from error

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
        or parsed.path not in {"", "/"}
        or parsed.netloc.endswith(":")
    ):
        raise ValueError(error_message)

    try:
        host = normalize_loopback_host(parsed.hostname)
    except ValueError as error:
        raise ValueError(error_message) from error

    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority = f"{authority}:{port}"
    return f"{parsed.scheme}://{authority}"


def main() -> None:
    host = normalize_loopback_host(os.environ.get("HOST", "127.0.0.1"))
    port = int(os.environ.get("PORT", "8080"))
    url_host = f"[{host}]" if ":" in host else host
    url = f"http://{url_host}:{port}"
    if os.environ.get("SWIPE_WEB_OPEN_BROWSER", "1") != "0":
        opener = threading.Timer(0.8, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    uvicorn.run("swipe_dating.web.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
