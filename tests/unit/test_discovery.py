from __future__ import annotations

import pytest

from swipe_dating.domain.discovery import (
    DEFAULT_RANKING_WEIGHTS,
    DiscoveryProfile,
    assert_ranking_input_safe,
    evaluate_discovery_candidate,
    normalize_ranking_weights,
    rank_discovery_candidates,
)
from swipe_dating.domain.errors import DomainError


def viewer() -> DiscoveryProfile:
    return DiscoveryProfile(
        id="viewer",
        immediate_intent="casual_dating",
        relational_openness="open_to_more",
        accepted_immediate_intents=("casual_dating", "friends_with_benefits"),
        accepted_relational_openness=("open_to_more", "relationship_possible"),
        boundaries=("condoms_required", "public_first_meet", "no_drugs"),
        required_boundaries=("condoms_required", "public_first_meet"),
        lifestyle_tags=("live_music", "hiking", "movie_night"),
        max_distance_km=40,
    )


def candidate(**overrides: object) -> DiscoveryProfile:
    values: dict[str, object] = {
        "id": "candidate-a",
        "immediate_intent": "friends_with_benefits",
        "relational_openness": "relationship_possible",
        "accepted_immediate_intents": ("casual_dating",),
        "accepted_relational_openness": ("open_to_more",),
        "boundaries": ("condoms_required", "public_first_meet", "no_drugs"),
        "required_boundaries": ("condoms_required",),
        "lifestyle_tags": ("live_music", "hiking"),
        "alignment_score": 84,
        "distance_km": 8,
    }
    values.update(overrides)
    return DiscoveryProfile(**values)  # type: ignore[arg-type]


def test_weights_normalize_to_exactly_one_hundred() -> None:
    weights = normalize_ranking_weights(
        {"intent": 9, "boundaries": 3, "lifestyle": 2, "alignment": 5, "distance": 1}
    )
    assert sum(weights.values()) == 100
    assert normalize_ranking_weights({}) == DEFAULT_RANKING_WEIGHTS
    assert normalize_ranking_weights({"intent": -10, "distance": "invalid"}) == (
        DEFAULT_RANKING_WEIGHTS
    )


def test_weights_remain_bounded_when_earlier_dimensions_round_up() -> None:
    assert normalize_ranking_weights(
        {"intent": 0, "boundaries": 0, "lifestyle": 10, "alignment": 70, "distance": 0}
    ) == {
        "intent": 0,
        "boundaries": 0,
        "lifestyle": 13,
        "alignment": 87,
        "distance": 0,
    }


@pytest.mark.parametrize(
    ("override", "exclusion"),
    [
        (
            {"accepted_relational_openness": ("casual_only",)},
            "candidate_does_not_accept_viewer_relational_openness",
        ),
        (
            {"accepted_immediate_intents": ("open_dating",)},
            "candidate_does_not_accept_viewer_immediate_intent",
        ),
        ({"boundaries": ("condoms_required",)}, "missing_boundary:public_first_meet"),
        (
            {"required_boundaries": ("sober_meetup",)},
            "viewer_missing_boundary:sober_meetup",
        ),
    ],
)
def test_mutual_eligibility_and_required_boundaries_are_hard_gates(
    override: dict[str, object], exclusion: str
) -> None:
    result = evaluate_discovery_candidate(viewer(), candidate(**override))
    assert result.eligible is False
    assert result.score == 0
    assert exclusion in result.exclusions


def test_gender_feed_filter_excludes_non_matching_identities() -> None:
    watching = DiscoveryProfile(
        id="viewer",
        immediate_intent="casual_dating",
        relational_openness="open_to_more",
        accepted_immediate_intents=("casual_dating", "friends_with_benefits"),
        accepted_relational_openness=("open_to_more", "relationship_possible"),
        boundaries=("condoms_required", "public_first_meet", "no_drugs"),
        required_boundaries=("condoms_required", "public_first_meet"),
        lifestyle_tags=("live_music", "hiking", "movie_night"),
        feed_genders=("man",),
        max_distance_km=40,
    )
    blocked = evaluate_discovery_candidate(watching, candidate(genders=("woman",)))
    assert blocked.eligible is False
    assert "gender_feed_mismatch" in blocked.exclusions
    allowed = evaluate_discovery_candidate(watching, candidate(genders=("man", "trans_man")))
    assert allowed.eligible is True


def test_eligible_candidate_has_explainable_fixed_weight_score() -> None:
    result = evaluate_discovery_candidate(viewer(), candidate())
    assert result.eligible
    assert 0 <= result.score <= 100
    assert len(result.explanation) == 5
    assert sum(item.weight for item in result.explanation) == 100


def test_fixed_weights_change_order_and_ties_use_candidate_id() -> None:
    close = candidate(id="close", lifestyle_tags=("gaming",), alignment_score=60, distance_km=1)
    aligned = candidate(
        id="aligned",
        lifestyle_tags=("live_music", "hiking", "movie_night"),
        alignment_score=98,
        distance_km=30,
    )
    distance_first = rank_discovery_candidates(
        viewer(),
        (aligned, close),
        {"intent": 0, "boundaries": 0, "lifestyle": 0, "alignment": 0, "distance": 100},
    )
    assert distance_first[0].candidate.id == "close"
    compatibility_first = rank_discovery_candidates(
        viewer(),
        (aligned, close),
        {"intent": 0, "boundaries": 0, "lifestyle": 50, "alignment": 50, "distance": 0},
    )
    assert compatibility_first[0].candidate.id == "aligned"
    tied = rank_discovery_candidates(
        viewer(),
        (candidate(id="z"), candidate(id="a")),
    )
    assert [entry.candidate.id for entry in tied] == ["a", "z"]


def test_forbidden_nested_ranking_fields_fail_closed() -> None:
    with pytest.raises(DomainError, match="forbidden_ranking_input"):
        assert_ranking_input_safe({"candidate": {"attractiveness": 90, "purchases": 4}})
    assert assert_ranking_input_safe({"candidate": {"alignmentScore": 90, "distanceKm": 3}})


@pytest.mark.parametrize(
    ("distance", "maximum", "component"),
    [(0, 40, 100), (40, 40, 0), (41, 40, 0), (-5, 40, 100)],
)
def test_distance_boundaries(distance: float, maximum: float, component: int) -> None:
    result = evaluate_discovery_candidate(
        viewer(), candidate(distance_km=distance), {"distance": 100}
    )
    distance_item = next(item for item in result.explanation if item.key == "distance")
    assert distance_item.component == component
