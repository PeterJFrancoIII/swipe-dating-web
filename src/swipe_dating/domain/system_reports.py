"""User-submitted in-app errors and feedback. Isolated from dating content."""

from __future__ import annotations

import json
import re
from typing import Any

ERROR_TITLE = "User Submitted In-App Errors"
SCREENSHOT_MAX_BYTES = 2 * 1024 * 1024
EXPLANATION_MAX_CHARS = 2000
FEEDBACK_MAX_CHARS = 2000
ERROR_RATE_LIMIT = 12
FEEDBACK_RATE_LIMIT = 8
RATE_WINDOW_MS = 24 * 60 * 60 * 1000
MAX_TAGS = 12
_TAG = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,31}$")
_SECRET = re.compile(r"(token|password|secret|cookie|authorization|session|identity_token)", re.I)

ALLOWED_CONTEXT_KEYS = frozenset(
    {
        "route",
        "screen",
        "app_version",
        "build_number",
        "platform",
        "os_version",
        "expo_sdk",
        "release",
        "adult_accepted",
        "onboarding_complete",
        "apple_bound",
        "account_id",
        "last_error",
        "match_id",
        "timezone",
        "client_time",
        "surface_href",
        "surface_label",
        "kind",
    }
)

SECURITY_HOLD_TAG = "security_hold"
SECURITY_HOLD_STATUS = "admin_only"
SECURITY_HOLD_NOTICE = "Security stays with admins. This was not added to the community queue."
COMMUNITY_BUG_NOTICE = "Saved for repair. Thank you."
COMMUNITY_FEATURE_NOTICE = "Feature request saved. Thank you."
_SECURITY_TERMS = (
    "cyber security",
    "cybersecurity",
    "encryption",
    "encrypt",
    "decrypt",
    "private key",
    "session token",
    "jwt",
    "app attest",
    "attestation bypass",
    "weaken encryption",
    "disable encryption",
    "bypass age",
    "disable age",
    "fail open",
    "operator password",
    "admin password",
    "/operator",
    "sql injection",
    "xss",
    "csrf",
    "rce",
    "0day",
    "zero-day",
    "exploit",
    "keylogger",
    "malware",
    "privilege escalation",
    "pentest",
    "penetration test",
    "csam",
)
ALLOWED_ERROR_KEYS = frozenset({"path", "status", "code", "message"})


def sanitize_tags(raw: Any) -> list[str]:
    values: list[str] = []
    if isinstance(raw, str):
        values = [part.strip() for part in raw.replace(";", ",").split(",")]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    clean: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = value.lower().replace(" ", "-")
        if not _TAG.match(tag) or tag in seen:
            continue
        seen.add(tag)
        clean.append(tag)
        if len(clean) >= MAX_TAGS:
            break
    return clean


def sanitize_context(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        if name not in ALLOWED_CONTEXT_KEYS or _SECRET.search(name):
            continue
        if name == "last_error" and isinstance(value, dict):
            clean[name] = {
                str(item): _clip(str(item_value), 240)
                for item, item_value in value.items()
                if str(item) in ALLOWED_ERROR_KEYS and not _SECRET.search(str(item))
            }
            continue
        if isinstance(value, bool):
            clean[name] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            clean[name] = value
        elif value is None:
            continue
        else:
            text = _clip(str(value), 180)
            if text:
                clean[name] = text
    return clean


def auto_tags(context: dict[str, Any], extra: list[str] | None = None) -> list[str]:
    tags = list(extra or [])
    screen = str(context.get("screen") or "").strip()
    if screen:
        tags.append(f"screen:{_slug(screen)}")
    route = str(context.get("route") or "").strip()
    if route:
        tags.append(f"route:{_slug(route)}")
    last = context.get("last_error")
    if isinstance(last, dict):
        code = str(last.get("code") or "").strip()
        status = str(last.get("status") or "").strip()
        if code:
            tags.append(f"code:{_slug(code)}")
        if status:
            tags.append(f"http:{_slug(status)}")
    platform = str(context.get("platform") or "").strip()
    if platform:
        tags.append(f"os:{_slug(platform)}")
    return sanitize_tags(tags)


def clip_explanation(value: Any) -> str:
    return _clip(str(value or ""), EXPLANATION_MAX_CHARS)


def clip_feedback(value: Any) -> str:
    return _clip(str(value or ""), FEEDBACK_MAX_CHARS)


def is_security_control_request(*parts: object) -> bool:
    haystack = " ".join(str(part or "") for part in parts).lower()
    return any(term in haystack for term in _SECURITY_TERMS)


def apply_security_hold(tags: list[str], *parts: object) -> tuple[list[str], str, bool]:
    held = is_security_control_request(*parts)
    next_tags = list(tags)
    if held and SECURITY_HOLD_TAG not in next_tags:
        next_tags.append(SECURITY_HOLD_TAG)
    status = SECURITY_HOLD_STATUS if held else "open"
    return sanitize_tags(next_tags), status, held


def community_digest(
    errors: list[dict[str, Any]],
    ideas: list[dict[str, Any]],
    *,
    since_ms: int,
) -> dict[str, Any]:
    def visible(item: dict[str, Any]) -> bool:
        tags = [str(tag) for tag in (item.get("tags") or [])]
        created = int(item.get("created_at") or 0)
        return created >= since_ms and SECURITY_HOLD_TAG not in tags

    def held(item: dict[str, Any]) -> bool:
        tags = [str(tag) for tag in (item.get("tags") or [])]
        created = int(item.get("created_at") or 0)
        return created >= since_ms and SECURITY_HOLD_TAG in tags

    bugs = [item for item in errors if visible(item)]
    features = [item for item in ideas if visible(item)]
    return {
        "bugs": bugs,
        "feature_requests": features,
        "admin_only_count": sum(1 for item in (*errors, *ideas) if held(item)),
    }


def screenshot_mime(payload: bytes) -> str:
    if len(payload) < 12 or len(payload) > SCREENSHOT_MAX_BYTES:
        return ""
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9:_-]+", "-", value.lower()).strip("-")[:32]


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    return text[:limit]
