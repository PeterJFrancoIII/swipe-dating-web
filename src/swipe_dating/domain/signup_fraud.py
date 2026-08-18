"""Fail-closed signup policy. IP is a velocity bucket only — never location."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping

SIGNUP_RATE_LIMITED = "signup_rate_limited"
SIGNUP_UNAUTHENTIC = "signup_unauthentic"
PHOTO_REUSED = "photo_reused"
APPLE_SIGN_IN_REQUIRED = "apple_sign_in_required"
SESSION_REQUIRED = "session_required"

INSTALL_HEADER = "X-Getfkd-Install"
UNKNOWN_BUCKET = "unknown"

HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS
WEEK_MS = 7 * DAY_MS

SESSIONS_PER_IP_HOUR = 8
UNKNOWN_SESSIONS_PER_HOUR = 4
AGE_GATES_PER_IP_HOUR = 20
ONBOARDS_PER_IP_DAY = 3
ONBOARDS_PER_INSTALL_WEEK = 2
UNKNOWN_ONBOARDS_PER_WEEK = 1
MIN_ONBOARDING_MS = 45_000

KIND_SESSION_MINT = "session_mint"
KIND_AGE_GATE = "age_gate"
KIND_AGE_FAIL = "age_fail"
KIND_ONBOARD_COMPLETE = "onboard_complete"
KIND_LOCK = "lock"

SIGNUP_MESSAGES = {
    SIGNUP_RATE_LIMITED: "Slow down and try again later.",
    SIGNUP_UNAUTHENTIC: "This signup could not be verified.",
    PHOTO_REUSED: "Choose a different photo.",
    APPLE_SIGN_IN_REQUIRED: "Sign in with Apple is required.",
    SESSION_REQUIRED: "Your session expired. Try again.",
}


class SignupFraudError(Exception):
    def __init__(self, code: str, *, status_code: int, lock: bool = False) -> None:
        self.code = code
        self.status_code = status_code
        self.lock = lock
        super().__init__(code)


def signup_relaxed_from_env() -> bool:
    return os.environ.get("GETFKD_SIGNUP_RELAXED", "").strip().lower() in {"1", "true", "yes"}


def dev_skip_apple_from_env() -> bool:
    return os.environ.get("GETFKD_DEV_SKIP_APPLE", "").strip().lower() in {"1", "true", "yes"}


def allows_dev_apple_bypass(enabled: bool, headers: Mapping[str, str]) -> bool:
    """Metro/dogfood only. Store and preview releases stay fail-closed."""
    if not enabled:
        return False
    return header_value(headers, "X-Getfkd-Release").lower() not in {"store", "preview"}


def signup_message(code: str) -> str:
    return SIGNUP_MESSAGES.get(code, SIGNUP_MESSAGES[SIGNUP_UNAUTHENTIC])


def hash_token(value: str) -> str:
    raw = value.strip().lower()
    if not raw:
        return UNKNOWN_BUCKET
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def photo_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def header_value(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value or "").strip()
    return ""


def client_ip(headers: Mapping[str, str]) -> str:
    forwarded = header_value(headers, "cf-connecting-ip") or header_value(headers, "x-real-ip")
    if not forwarded:
        return ""
    return forwarded.split(",")[0].strip()


def install_id(headers: Mapping[str, str]) -> str:
    return header_value(headers, INSTALL_HEADER)


def birth_key_from_date(submitted: str) -> str:
    return f"date:{submitted.strip()}"


def birth_key_from_range(lower_bound: int) -> str:
    return f"range:{int(lower_bound)}"


def session_mint_cap(ip_hash: str) -> int:
    return UNKNOWN_SESSIONS_PER_HOUR if ip_hash == UNKNOWN_BUCKET else SESSIONS_PER_IP_HOUR


def onboard_install_cap(install_hash: str) -> int:
    return UNKNOWN_ONBOARDS_PER_WEEK if install_hash == UNKNOWN_BUCKET else ONBOARDS_PER_INSTALL_WEEK


def assert_birth_frozen(existing: str, incoming: str) -> None:
    if existing and incoming and existing != incoming:
        raise SignupFraudError(SIGNUP_UNAUTHENTIC, status_code=403, lock=True)
