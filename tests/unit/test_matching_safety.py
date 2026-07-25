from __future__ import annotations

import pytest

from swipe_dating.domain.adult import create_adult_credential
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.location_grants import (
    LocationMode,
    issue_location_grant,
    location_grant_is_active,
    revoke_location_grant,
)
from swipe_dating.domain.matching import RendezvousStore
from swipe_dating.domain.proximity import (
    ProximityDecision,
    ProximityDisclosure,
    decide_proximity_event,
)
from swipe_dating.domain.risk import RiskAction, assess_risk
from swipe_dating.domain.skin_shop import validate_skin_manifest

NOW = 1_700_000_000_000


def credential(subject_id: str, *, revoked: bool = False):  # type: ignore[no-untyped-def]
    return create_adult_credential(
        subject_id=subject_id,
        issued_at_ms=NOW,
        expires_at_ms=NOW + 3_600_000,
        revoked=revoked,
    )


def publish(store: RendezvousStore, profile_id: str, *, ttl_ms: int = 120_000) -> None:
    store.publish_presence(
        profile_id=profile_id,
        region="rnd:test",
        issued_at_ms=NOW,
        expires_at_ms=NOW + ttl_ms,
        adult_credential=credential(profile_id),
    )


def test_rendezvous_is_ephemeral_subject_bound_and_reciprocal() -> None:
    store = RendezvousStore()
    with pytest.raises(DomainError, match="adult_credential_subject_bound"):
        store.publish_presence(
            profile_id="a",
            region="rnd:test",
            issued_at_ms=NOW,
            expires_at_ms=NOW + 1,
            adult_credential=credential("b"),
        )
    publish(store, "a")
    publish(store, "b")
    assert store.discover(region="rnd:test", requester_profile_id="a", now_ms=NOW) == ("b",)
    assert store.record_like(sender_profile_id="a", recipient_profile_id="b", now_ms=NOW) is None
    receipt = store.record_like(sender_profile_id="b", recipient_profile_id="a", now_ms=NOW)
    assert receipt is not None
    assert (receipt.profile_a, receipt.profile_b, receipt.matched_at_ms) == ("a", "b", NOW)
    assert store.withdraw_presence("b") is True
    assert store.discover(region="rnd:test", requester_profile_id="a", now_ms=NOW) == ()


@pytest.mark.parametrize("ttl_ms", [0, 120_001])
def test_presence_rejects_invalid_ttl(ttl_ms: int) -> None:
    with pytest.raises(DomainError, match="presence_ttl_out_of_range"):
        publish(RendezvousStore(), "a", ttl_ms=ttl_ms)


@pytest.mark.parametrize("region", ["", "x" * 65, "city,block"])
def test_presence_rejects_invalid_regions(region: str) -> None:
    with pytest.raises(DomainError, match="invalid_coarse_region"):
        RendezvousStore().publish_presence(
            profile_id="a",
            region=region,
            issued_at_ms=NOW,
            expires_at_ms=NOW + 1,
            adult_credential=credential("a"),
        )


def test_discovery_expires_sorts_clamps_and_blocks() -> None:
    store = RendezvousStore()
    for profile_id in ("z", "a", "m", "viewer"):
        publish(store, profile_id, ttl_ms=10)
    assert store.discover(
        region="rnd:test", requester_profile_id="viewer", now_ms=NOW, limit=2
    ) == ("a", "m")
    store.block(blocker_profile_id="viewer", blocked_profile_id="a")
    assert store.discover(
        region="rnd:test", requester_profile_id="viewer", now_ms=NOW, limit=20
    ) == ("m", "z")
    assert store.discover(region="rnd:test", requester_profile_id="viewer", now_ms=NOW + 10) == ()


def test_self_and_blocked_interactions_fail_closed() -> None:
    store = RendezvousStore()
    with pytest.raises(DomainError, match="cannot_like_self"):
        store.record_like(sender_profile_id="a", recipient_profile_id="a", now_ms=NOW)
    with pytest.raises(DomainError, match="cannot_block_self"):
        store.block(blocker_profile_id="a", blocked_profile_id="a")
    store.record_like(sender_profile_id="a", recipient_profile_id="b", now_ms=NOW)
    store.block(blocker_profile_id="b", blocked_profile_id="a")
    with pytest.raises(DomainError, match="interaction_blocked"):
        store.record_like(sender_profile_id="a", recipient_profile_id="b", now_ms=NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"adult_credential_valid": False},
        {"disclosure": ProximityDisclosure.OFF},
        {"emergency_privacy": True},
        {"blocked": True},
        {"within_haptic_cooldown": True},
    ],
)
def test_proximity_suppression_conditions(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "adult_credential_valid": True,
        "disclosure": ProximityDisclosure.PROMPT_BEFORE_SHARING,
        "independently_compatible": True,
    }
    values.update(overrides)
    assert decide_proximity_event(**values) is ProximityDecision.SUPPRESS  # type: ignore[arg-type]


def test_proximity_disclosure_outcomes() -> None:
    assert (
        decide_proximity_event(
            adult_credential_valid=True,
            disclosure=ProximityDisclosure.PROMPT_BEFORE_SHARING,
            independently_compatible=False,
        )
        is ProximityDecision.BUZZ_ONLY
    )
    assert (
        decide_proximity_event(
            adult_credential_valid=True,
            disclosure=ProximityDisclosure.PROMPT_BEFORE_SHARING,
            independently_compatible=True,
        )
        is ProximityDecision.BUZZ_AND_PROMPT
    )
    assert (
        decide_proximity_event(
            adult_credential_valid=True,
            disclosure=ProximityDisclosure.AUTO_SHARE_COMPATIBLE,
            independently_compatible=True,
        )
        is ProximityDecision.BUZZ_AND_SHARE_SCOPED_CAPABILITY
    )


def test_location_grants_require_second_confirmation_expire_and_revoke() -> None:
    with pytest.raises(DomainError, match="precise_confirmation_required"):
        issue_location_grant(
            share_id="s1",
            sender_profile_id="a",
            recipient_profile_id="b",
            mode=LocationMode.LIVE_15_MINUTES,
            issued_at_ms=1_000,
            sequence=1,
        )
    grant = issue_location_grant(
        share_id="s1",
        sender_profile_id="a",
        recipient_profile_id="b",
        mode=LocationMode.LIVE_15_MINUTES,
        issued_at_ms=1_000,
        sequence=1,
        precise_confirmation=True,
    )
    assert location_grant_is_active(grant, 1_000)
    assert location_grant_is_active(grant, 1_000 + 15 * 60_000 - 1)
    assert not location_grant_is_active(grant, 1_000 + 15 * 60_000)
    revoked = revoke_location_grant(grant, 2_000)
    assert revoked.sequence == 2
    assert not location_grant_is_active(revoked, 2_000)
    with pytest.raises(DomainError, match="invalid_revocation_time"):
        revoke_location_grant(grant, 999)


def test_location_approximate_mode_does_not_require_precise_confirmation() -> None:
    grant = issue_location_grant(
        share_id="s",
        sender_profile_id="a",
        recipient_profile_id="b",
        mode=LocationMode.APPROXIMATE_MATCH_AREA,
        issued_at_ms=0,
        sequence=0,
    )
    assert grant.expires_at_ms == 24 * 60 * 60 * 1_000


def test_risk_thresholds_and_immediate_denials() -> None:
    assert assess_risk({"adultCredentialValid": False}).action is RiskAction.DENY
    assert (
        assess_risk({"adultCredentialValid": True, "attestation": "failed"}).action
        is RiskAction.DENY
    )
    assert (
        assess_risk(
            {
                "adultCredentialValid": True,
                "attestation": "hardware_backed",
                "discoveryRequestsMinute": 4,
                "likesMinute": 2,
            }
        ).action
        is RiskAction.ALLOW
    )
    assert (
        assess_risk(
            {
                "adultCredentialValid": True,
                "attestation": "missing",
            }
        ).action
        is RiskAction.THROTTLE
    )
    assert (
        assess_risk(
            {
                "adultCredentialValid": True,
                "attestation": "unsupported",
                "discoveryRequestsMinute": 500,
                "profileFetchesMinute": 500,
                "bleReplayHits24h": 2,
            }
        ).action
        is RiskAction.TEMPORARY_CONTAINMENT
    )


def test_skin_manifest_accumulates_rejection_reasons() -> None:
    result = validate_skin_manifest(
        {
            "assetId": "x",
            "creatorId": "c",
            "mimeType": "text/html",
            "byteLength": 9 * 1024 * 1024,
            "width": 5000,
            "height": 0,
            "frameCount": 0,
            "integritySha256": "bad",
            "remoteReferences": ["https://example.invalid/script.js"],
        }
    )
    assert result.valid is False
    assert result.reasons == (
        "mime_not_allowed",
        "byte_limit",
        "dimension_limit",
        "frame_limit",
        "invalid_integrity_hash",
        "remote_references_forbidden",
    )


def test_valid_skin_manifest_passes() -> None:
    result = validate_skin_manifest(
        {
            "assetId": "skin",
            "creatorId": "creator",
            "mimeType": "image/png",
            "byteLength": 1024,
            "width": 512,
            "height": 512,
            "frameCount": 1,
            "integritySha256": "a" * 64,
            "remoteReferences": [],
        }
    )
    assert result.valid
    assert result.reasons == ()
