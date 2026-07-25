"""Content-blind synthetic abuse-risk decisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class RiskAction(StrEnum):
    ALLOW = "allow"
    THROTTLE = "throttle"
    CHALLENGE = "challenge"
    TEMPORARY_CONTAINMENT = "temporary_containment"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    score: int
    action: RiskAction
    reasons: tuple[str, ...]


def assess_risk(signals: Mapping[str, object]) -> RiskAssessment:
    if signals.get("adultCredentialValid") is not True:
        return RiskAssessment(100, RiskAction.DENY, ("adult_credential_invalid",))
    if signals.get("attestation") == "failed":
        return RiskAssessment(100, RiskAction.DENY, ("attestation_failed",))

    score = 0
    reasons: list[str] = []
    attestation_penalty = {
        "hardware_backed": 0,
        "software_fallback": 8,
        "unsupported": 20,
        "missing": 30,
    }.get(str(signals.get("attestation", "unsupported")), 25)
    if attestation_penalty:
        score += attestation_penalty
        reasons.append("lower_trust_device")

    def add(condition: bool, points: int, reason: str) -> None:
        nonlocal score
        if condition:
            score += points
            reasons.append(reason)

    accounts = _number(signals, "accountsCreated24h")
    add(accounts > 2, min(48, int((accounts - 2) * 12)), "mass_registration")
    add(_number(signals, "presencePublishesMinute") > 12, 20, "presence_flood")
    add(_number(signals, "discoveryRequestsMinute") > 120, 20, "discovery_scraping")
    add(_number(signals, "profileFetchesMinute") > 100, 25, "profile_scraping")
    add(_number(signals, "likesMinute") > 60, 25, "automated_liking")
    replay_hits = _number(signals, "bleReplayHits24h")
    add(replay_hits > 0, min(40, int(replay_hits * 10)), "ble_replay")
    add(signals.get("impossibleTravel") is True, 25, "impossible_travel")
    malicious_hits = _number(signals, "maliciousLinkHits24h")
    add(malicious_hits > 0, min(40, int(malicious_hits * 20)), "malicious_links")
    add(_number(signals, "reportBrigadeScore") > 50, 20, "report_brigading")
    enforcement = _number(signals, "priorEnforcementCount")
    add(enforcement > 0, min(30, int(enforcement * 10)), "prior_enforcement")

    score = min(100, score)
    if score >= 80:
        action = RiskAction.TEMPORARY_CONTAINMENT
    elif score >= 55:
        action = RiskAction.CHALLENGE
    elif score >= 30:
        action = RiskAction.THROTTLE
    else:
        action = RiskAction.ALLOW
    return RiskAssessment(score, action, tuple(reasons))


def _number(signals: Mapping[str, object], key: str) -> float:
    value = signals.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return float(value)
