"""Reproduce the pinned JavaScript simulator without external services."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from swipe_dating import RELEASE_STATE
from swipe_dating.adapters.crypto.identifiers import derive_rotating_encounter_id
from swipe_dating.domain.adult import create_adult_credential, is_adult_on
from swipe_dating.domain.alignment import AlignmentAnswer, AlignmentProfile, score_alignment
from swipe_dating.domain.matching import RendezvousStore
from swipe_dating.domain.proximity import ProximityDisclosure, decide_proximity_event
from swipe_dating.domain.risk import assess_risk


def run_scenario() -> dict[str, Any]:
    now_ms = int(datetime(2026, 7, 21, 16, tzinfo=UTC).timestamp() * 1_000)
    store = RendezvousStore()

    def credential(subject_id: str):  # type: ignore[no-untyped-def]
        return create_adult_credential(
            subject_id=subject_id,
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + 3_600_000,
        )

    for profile_id in ("alice", "bob"):
        store.publish_presence(
            profile_id=profile_id,
            region="rnd:test-region",
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + 120_000,
            adult_credential=credential(profile_id),
        )
    first_like = store.record_like(
        sender_profile_id="alice", recipient_profile_id="bob", now_ms=now_ms
    )
    reciprocal_like = store.record_like(
        sender_profile_id="bob", recipient_profile_id="alice", now_ms=now_ms
    )
    alignment = score_alignment(
        AlignmentProfile(
            "alignment-us-en-v1",
            {
                "relationship": AlignmentAnswer("dating", importance=5),
                "health_money": AlignmentAnswer("balance", importance=4),
            },
        ),
        AlignmentProfile(
            "alignment-us-en-v1",
            {
                "relationship": AlignmentAnswer("dating", importance=4),
                "health_money": AlignmentAnswer("balance", importance=5),
            },
        ),
    )
    risk = assess_risk(
        {
            "adultCredentialValid": True,
            "attestation": "hardware_backed",
            "discoveryRequestsMinute": 8,
            "likesMinute": 2,
        }
    )
    return {
        "runtime": "Python",
        "syntheticOnly": True,
        "releaseState": RELEASE_STATE,
        "adultBoundary": {
            "turns18Today": is_adult_on("2008-07-21", "2026-07-21"),
            "turns18Tomorrow": is_adult_on("2008-07-22", "2026-07-21"),
        },
        "discoveryForAlice": list(
            store.discover(region="rnd:test-region", requester_profile_id="alice", now_ms=now_ms)
        ),
        "firstLikeMatches": first_like is not None,
        "reciprocalLikeMatches": reciprocal_like is not None,
        "alignmentPercent": alignment.score_percent,
        "proximityDecision": decide_proximity_event(
            adult_credential_valid=True,
            disclosure=ProximityDisclosure.PROMPT_BEFORE_SHARING,
            independently_compatible=True,
        ).value,
        "rotatingEncounterId": derive_rotating_encounter_id(
            secret=bytes([7]) * 32,
            epoch=1,
            session_nonce_hex="01" * 16,
        ),
        "botRisk": {
            "score": risk.score,
            "action": risk.action.value,
            "reasons": list(risk.reasons),
        },
    }


def main() -> None:
    print(json.dumps(run_scenario(), indent=2))


if __name__ == "__main__":
    main()
