"""Mutual-intent eligibility, hard boundaries, and fixed transparent rank."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Final

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.models import js_round

IMMEDIATE_INTENTS: Final = (
    "casual_tonight",
    "friends_with_benefits",
    "casual_dating",
    "open_dating",
    "relationship_focused",
    "figuring_it_out",
)

RELATIONAL_OPENNESS: Final = (
    "casual_only",
    "open_to_more",
    "relationship_possible",
    "seeking_relationship",
)

BOUNDARY_TAGS: Final = (
    "condoms_required",
    "recent_testing_discussion",
    "public_first_meet",
    "sober_meetup",
    "no_group_encounters",
    "group_encounter_open",
    "no_smoking",
    "no_drugs",
)

RANKING_DIMENSIONS: Final = ("intent", "boundaries", "lifestyle", "alignment", "distance")
DEFAULT_RANKING_WEIGHTS: Final = {
    "intent": 30,
    "boundaries": 25,
    "lifestyle": 15,
    "alignment": 20,
    "distance": 10,
}

FORBIDDEN_RANKING_KEYS: Final = frozenset(
    {
        "race",
        "ethnicity",
        "skinColor",
        "skin_color",
        "disability",
        "height",
        "attractiveness",
        "intelligence",
        "hygiene",
        "sexuality",
        "gender",
        "fitness",
        "grooming",
        "bodyHair",
        "body_hair",
        "spending",
        "purchases",
        "popularity",
        "subscriptionStatus",
        "subscription_status",
        "creatorStatus",
        "creator_status",
    }
)


@dataclass(frozen=True, slots=True)
class DiscoveryProfile:
    id: str
    immediate_intent: str
    relational_openness: str
    accepted_immediate_intents: tuple[str, ...]
    accepted_relational_openness: tuple[str, ...]
    boundaries: tuple[str, ...]
    required_boundaries: tuple[str, ...]
    lifestyle_tags: tuple[str, ...]
    alignment_score: float = 0
    distance_km: float = 0
    max_distance_km: float = 40
    display_name: str = "Synthetic profile"
    age_band: str = "adult"
    about: str = ""
    synthetic_reciprocal_like: bool = False

    def __post_init__(self) -> None:
        for name in (
            "accepted_immediate_intents",
            "accepted_relational_openness",
            "boundaries",
            "required_boundaries",
            "lifestyle_tags",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class ScoreExplanation:
    key: str
    component: int
    weight: int


@dataclass(frozen=True, slots=True)
class DiscoveryEvaluation:
    eligible: bool
    score: int
    exclusions: tuple[str, ...]
    explanation: tuple[ScoreExplanation, ...]


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: DiscoveryProfile
    result: DiscoveryEvaluation


def normalize_ranking_weights(
    values: Mapping[str, object] | None = None,
) -> dict[str, int]:
    source = DEFAULT_RANKING_WEIGHTS if values is None else values
    weights = {key: _clamp_number(source.get(key), 0, 100) for key in RANKING_DIMENSIONS}
    total = sum(weights.values())
    if total == 0:
        return dict(DEFAULT_RANKING_WEIGHTS)

    exact = {key: weights[key] / total * 100 for key in RANKING_DIMENSIONS}
    normalized = {key: math.floor(exact[key]) for key in RANKING_DIMENSIONS}
    remaining = 100 - sum(normalized.values())
    allocation_order = sorted(
        enumerate(RANKING_DIMENSIONS),
        key=lambda item: (
            -(exact[item[1]] - normalized[item[1]]),
            item[0],
        ),
    )
    for _index, key in allocation_order[:remaining]:
        normalized[key] += 1
    return normalized


def assert_ranking_input_safe(value: object) -> bool:
    keys = _collect_keys(value)
    forbidden = sorted(FORBIDDEN_RANKING_KEYS.intersection(keys))
    if forbidden:
        raise DomainError("forbidden_ranking_input", ", ".join(forbidden))
    return True


def evaluate_discovery_candidate(
    viewer: DiscoveryProfile,
    candidate: DiscoveryProfile,
    weights: Mapping[str, object] | None = None,
) -> DiscoveryEvaluation:
    assert_ranking_input_safe({"viewer": viewer, "candidate": candidate})
    normalized_weights = normalize_ranking_weights(weights)
    exclusions: list[str] = []
    if viewer.immediate_intent not in candidate.accepted_immediate_intents:
        exclusions.append("candidate_does_not_accept_viewer_immediate_intent")
    if candidate.immediate_intent not in viewer.accepted_immediate_intents:
        exclusions.append("viewer_does_not_accept_candidate_immediate_intent")
    if viewer.relational_openness not in candidate.accepted_relational_openness:
        exclusions.append("candidate_does_not_accept_viewer_relational_openness")
    if candidate.relational_openness not in viewer.accepted_relational_openness:
        exclusions.append("viewer_does_not_accept_candidate_relational_openness")

    candidate_boundaries = set(candidate.boundaries)
    exclusions.extend(
        f"missing_boundary:{boundary}"
        for boundary in viewer.required_boundaries
        if boundary not in candidate_boundaries
    )
    viewer_boundaries = set(viewer.boundaries)
    exclusions.extend(
        f"viewer_missing_boundary:{boundary}"
        for boundary in candidate.required_boundaries
        if boundary not in viewer_boundaries
    )

    if exclusions:
        return DiscoveryEvaluation(False, 0, tuple(exclusions), ())

    components = {
        "intent": _intent_compatibility(viewer, candidate),
        "boundaries": _set_overlap_score(viewer.boundaries, candidate.boundaries),
        "lifestyle": _set_overlap_score(viewer.lifestyle_tags, candidate.lifestyle_tags),
        "alignment": int(_clamp_number(candidate.alignment_score, 0, 100)),
        "distance": _distance_score(candidate.distance_km, viewer.max_distance_km),
    }
    score = js_round(
        sum(components[key] * normalized_weights[key] / 100 for key in RANKING_DIMENSIONS)
    )
    explanation = tuple(
        sorted(
            (
                ScoreExplanation(key, components[key], normalized_weights[key])
                for key in RANKING_DIMENSIONS
            ),
            key=lambda item: -(item.component * item.weight),
        )
    )
    return DiscoveryEvaluation(True, score, (), explanation)


def rank_discovery_candidates(
    viewer: DiscoveryProfile,
    candidates: Sequence[DiscoveryProfile],
    weights: Mapping[str, object] | None = None,
) -> tuple[RankedCandidate, ...]:
    results = (
        RankedCandidate(candidate, evaluate_discovery_candidate(viewer, candidate, weights))
        for candidate in candidates
    )
    return tuple(
        sorted(
            (entry for entry in results if entry.result.eligible),
            key=lambda entry: (-entry.result.score, entry.candidate.id),
        )
    )


def _intent_compatibility(viewer: DiscoveryProfile, candidate: DiscoveryProfile) -> int:
    score = 50
    if viewer.immediate_intent == candidate.immediate_intent:
        score += 30
    if viewer.relational_openness == candidate.relational_openness:
        score += 20
    return int(_clamp_number(score, 0, 100))


def _set_overlap_score(left: Sequence[str], right: Sequence[str]) -> int:
    first = set(left)
    second = set(right)
    if not first and not second:
        return 50
    union = first | second
    return js_round(len(first & second) / max(1, len(union)) * 100)


def _distance_score(distance_km: object, max_distance_km: object) -> int:
    maximum = _clamp_number(max_distance_km, 1, 500)
    distance = _clamp_number(distance_km, 0, 10_000)
    if distance > maximum:
        return 0
    return js_round((1 - distance / maximum) * 100)


def _clamp_number(value: object, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return minimum
    try:
        number = float(value)  # JavaScript Number-style coercion for parity.
    except (TypeError, ValueError):
        return minimum
    if not math.isfinite(number):
        return minimum
    return min(maximum, max(minimum, number))


def _collect_keys(value: object, keys: set[str] | None = None) -> set[str]:
    result = set() if keys is None else keys
    if isinstance(value, Mapping):
        for key, child in value.items():
            result.add(str(key))
            _collect_keys(child, result)
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            result.add(field.name)
            _collect_keys(getattr(value, field.name), result)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _collect_keys(child, result)
    return result
