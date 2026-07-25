from __future__ import annotations

import pytest

from swipe_dating.adapters.crypto.identifiers import (
    derive_pairwise_quota_key,
    derive_rotating_encounter_id,
    random_session_nonce,
)
from swipe_dating.domain.errors import DomainError


def test_identifiers_match_javascript_golden_values() -> None:
    assert (
        derive_rotating_encounter_id(
            secret=bytes([7]) * 32,
            epoch=10,
            session_nonce_hex="01" * 16,
        )
        == "e551c70467a7ce4b8e8472a0cb78b342"
    )
    assert (
        derive_pairwise_quota_key(
            server_secret=bytes([9]) * 32,
            service="discovery",
            subject_token="opaque-user-token",
            epoch=1,
        )
        == "3027535353cf802e0772730e9dd26851faba0241b5bd55681e920b2a718fced7"
    )


def test_identifiers_rotate_by_epoch_session_and_service() -> None:
    first = derive_rotating_encounter_id(
        secret=bytes([7]) * 32, epoch=10, session_nonce_hex="01" * 16
    )
    assert first != derive_rotating_encounter_id(
        secret=bytes([7]) * 32, epoch=11, session_nonce_hex="01" * 16
    )
    assert first != derive_rotating_encounter_id(
        secret=bytes([7]) * 32, epoch=10, session_nonce_hex="02" * 16
    )
    quota = derive_pairwise_quota_key(
        server_secret=bytes([9]) * 32,
        service="discovery",
        subject_token="opaque-user-token",
        epoch=1,
    )
    assert quota != derive_pairwise_quota_key(
        server_secret=bytes([9]) * 32,
        service="likes",
        subject_token="opaque-user-token",
        epoch=1,
    )


def test_nonce_shape_and_invalid_crypto_inputs() -> None:
    nonce = random_session_nonce()
    assert len(nonce) == 32
    int(nonce, 16)
    with pytest.raises(DomainError, match="secret_too_short"):
        derive_rotating_encounter_id(secret=b"short", epoch=1, session_nonce_hex="01" * 16)
    with pytest.raises(DomainError, match="invalid_epoch"):
        derive_rotating_encounter_id(secret=bytes(32), epoch=-1, session_nonce_hex="01" * 16)
    with pytest.raises(DomainError, match="invalid_session_nonce"):
        derive_rotating_encounter_id(secret=bytes(32), epoch=1, session_nonce_hex="not-hex")
