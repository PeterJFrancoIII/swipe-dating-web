"""HMAC helpers ported for deterministic synthetic parity only."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.models import is_safe_integer

_NONCE = re.compile(r"^[a-f0-9]{32}$", re.IGNORECASE)


def random_session_nonce() -> str:
    return secrets.token_hex(16)


def derive_rotating_encounter_id(
    *,
    secret: bytes,
    epoch: int,
    session_nonce_hex: str,
) -> str:
    _validate_secret(secret, "secret")
    _validate_epoch(epoch)
    if not isinstance(session_nonce_hex, str) or _NONCE.fullmatch(session_nonce_hex) is None:
        raise DomainError("invalid_session_nonce")
    payload = (
        b"swipe-rnd-proximity-v1\0" + epoch.to_bytes(8, "big") + bytes.fromhex(session_nonce_hex)
    )
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()[:32]


def derive_pairwise_quota_key(
    *,
    server_secret: bytes,
    service: str,
    subject_token: str,
    epoch: int,
) -> str:
    _validate_secret(server_secret, "server_secret")
    if not service or not subject_token:
        raise DomainError("quota_scope_required")
    _validate_epoch(epoch)
    payload = (
        b"swipe-rnd-quota-v1\0"
        + service.encode()
        + b"\0"
        + subject_token.encode()
        + b"\0"
        + epoch.to_bytes(8, "big")
    )
    return hmac.new(server_secret, payload, hashlib.sha256).hexdigest()


def _validate_secret(value: bytes, name: str) -> None:
    if not isinstance(value, bytes) or len(value) < 32:
        raise DomainError("secret_too_short", name)


def _validate_epoch(value: int) -> None:
    if not is_safe_integer(value) or value < 0:
        raise DomainError("invalid_epoch")
