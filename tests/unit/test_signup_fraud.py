from __future__ import annotations

import pytest

from swipe_dating.domain.signup_fraud import (
    UNKNOWN_BUCKET,
    SignupFraudError,
    allows_dev_apple_bypass,
    assert_birth_frozen,
    birth_key_from_date,
    birth_key_from_range,
    client_ip,
    hash_token,
    photo_sha256,
    session_mint_cap,
    signup_message,
)


def test_client_ip_prefers_cloudflare_and_is_not_location() -> None:
    assert client_ip({"CF-Connecting-IP": "203.0.113.9", "X-Real-IP": "10.0.0.2"}) == "203.0.113.9"
    assert client_ip({"X-Real-IP": "198.51.100.4, 10.0.0.1"}) == "198.51.100.4"
    assert client_ip({}) == ""
    assert hash_token("") == UNKNOWN_BUCKET
    assert hash_token("203.0.113.9") != "203.0.113.9"


def test_unknown_ip_uses_stricter_session_cap() -> None:
    assert session_mint_cap(UNKNOWN_BUCKET) == 4
    assert session_mint_cap(hash_token("203.0.113.9")) == 8


def test_birth_date_freeze_fails_closed() -> None:
    assert_birth_frozen("", "date:2000-01-01")
    assert_birth_frozen("date:2000-01-01", "date:2000-01-01")
    with pytest.raises(SignupFraudError) as error:
        assert_birth_frozen("date:2008-01-01", "date:2000-01-01")
    assert error.value.code == "signup_unauthentic"
    assert error.value.lock is True
    assert birth_key_from_date("2000-01-01") != birth_key_from_range(18)


def test_dev_apple_bypass_skips_metro_not_store() -> None:
    assert allows_dev_apple_bypass(False, {}) is False
    assert allows_dev_apple_bypass(True, {}) is True
    assert allows_dev_apple_bypass(True, {"X-Getfkd-Release": "store"}) is False
    assert allows_dev_apple_bypass(True, {"X-Getfkd-Release": "preview"}) is False
    assert allows_dev_apple_bypass(True, {"X-Getfkd-Release": "dev"}) is True


def test_photo_hash_is_exact_bytes_only() -> None:
    assert photo_sha256(b"a") != photo_sha256(b"b")
    assert signup_message("signup_unauthentic") == "This signup could not be verified."
    assert signup_message("signup_rate_limited") == "Slow down and try again later."
    assert signup_message("session_required") == "Your session expired. Try again."
