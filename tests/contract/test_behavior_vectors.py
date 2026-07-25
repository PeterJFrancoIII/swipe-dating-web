from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from swipe_dating.adapters.crypto.identifiers import (
    derive_pairwise_quota_key,
    derive_rotating_encounter_id,
)
from swipe_dating.domain.adult import is_adult_on
from swipe_dating.domain.discovery import (
    evaluate_discovery_candidate,
    normalize_ranking_weights,
)
from swipe_dating.domain.location_grants import LocationMode, issue_location_grant
from swipe_dating.domain.proximity import ProximityDisclosure, decide_proximity_event
from swipe_dating.domain.risk import assess_risk
from swipe_dating.fixtures import GOLDEN_CANDIDATE, GOLDEN_VIEWER
from swipe_dating.simulation.run import run_scenario

VECTORS = Path(__file__).parents[1] / "fixtures" / "behavior_vectors.json"


def test_pinned_javascript_behavior_vectors_replay_in_python() -> None:
    expected = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert expected["metadata"]["sourceCommit"] == ("5c6b35e8b133f4b34224785eb4fc1e7ab61423a4")
    assert [
        is_adult_on("2008-07-22", "2026-07-21"),
        is_adult_on("2008-07-21", "2026-07-21"),
        is_adult_on("2008-02-29", "2026-02-28"),
    ] == expected["adult"]
    assert (
        normalize_ranking_weights(
            {"intent": 9, "boundaries": 3, "lifestyle": 2, "alignment": 5, "distance": 1}
        )
        == expected["weights"]
    )

    discovery = evaluate_discovery_candidate(GOLDEN_VIEWER, GOLDEN_CANDIDATE)
    assert {
        "eligible": discovery.eligible,
        "score": discovery.score,
        "exclusions": list(discovery.exclusions),
        "explanation": [asdict(item) for item in discovery.explanation],
    } == expected["discovery"]
    assert (
        decide_proximity_event(
            adult_credential_valid=True,
            disclosure=ProximityDisclosure.PROMPT_BEFORE_SHARING,
            independently_compatible=True,
        ).value
        == expected["proximity"]
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
    assert {
        "shareId": grant.share_id,
        "senderProfileId": grant.sender_profile_id,
        "recipientProfileId": grant.recipient_profile_id,
        "mode": grant.mode.value,
        "issuedAtMs": grant.issued_at_ms,
        "expiresAtMs": grant.expires_at_ms,
        "sequence": grant.sequence,
        "preciseConfirmation": grant.precise_confirmation,
        "revokedAtMs": grant.revoked_at_ms,
    } == expected["location"]
    risk = assess_risk({"adultCredentialValid": True, "attestation": "missing"})
    assert {"score": risk.score, "action": risk.action.value, "reasons": list(risk.reasons)} == (
        expected["risk"]
    )
    assert (
        derive_rotating_encounter_id(secret=bytes([7]) * 32, epoch=10, session_nonce_hex="01" * 16)
        == expected["encounter"]
    )
    assert (
        derive_pairwise_quota_key(
            server_secret=bytes([9]) * 32,
            service="discovery",
            subject_token="opaque-user-token",
            epoch=1,
        )
        == expected["quota"]
    )


def test_simulation_is_deterministic_and_honestly_labeled() -> None:
    first = run_scenario()
    assert first == run_scenario()
    assert first["runtime"] == "Python"
    assert first["syntheticOnly"] is True
    assert first["firstLikeMatches"] is False
    assert first["reciprocalLikeMatches"] is True
    assert first["releaseState"] == "PYTHON_RND_SYNTHETIC_ONLY"
