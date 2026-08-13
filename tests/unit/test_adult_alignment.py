from __future__ import annotations

import pytest

from swipe_dating.domain.adult import (
    adult_credential_is_valid,
    completed_age_years,
    create_adult_credential,
    is_adult_on,
    parse_date_only,
)
from swipe_dating.domain.alignment import AlignmentAnswer, AlignmentProfile, score_alignment
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.preferences import filter_key_allowed, intents_are_compatible


@pytest.mark.parametrize(
    ("birth_date", "on_date", "expected"),
    [
        ("2008-07-22", "2026-07-21", False),
        ("2008-07-21", "2026-07-21", True),
        ("2008-07-20", "2026-07-21", True),
        ("2008-02-29", "2026-02-27", False),
        ("2008-02-29", "2026-02-28", True),
        ("2004-02-29", "2022-02-28", True),
        ("not-a-date", "2026-07-21", False),
        ("2027-01-01", "2026-01-01", False),
    ],
)
def test_exact_adult_boundary(birth_date: str, on_date: str, expected: bool) -> None:
    assert is_adult_on(birth_date, on_date) is expected


def test_completed_age_years_uses_the_calendar_birthday() -> None:
    assert completed_age_years("2000-01-02", "2026-01-01") == 25
    assert completed_age_years("2000-01-01", "2026-01-01") == 26
    assert completed_age_years("not-a-date", "2026-01-01") is None
    assert completed_age_years("2027-01-01", "2026-01-01") is None


def test_date_only_parser_rejects_calendar_and_shape_errors() -> None:
    assert parse_date_only("2026-02-29") is None
    assert parse_date_only("2026-7-01") is None
    assert parse_date_only("2026-07-01T00:00:00Z") is None
    assert parse_date_only("2024-02-29") is not None


def test_adult_credentials_are_subject_bound_time_bounded_and_revocable() -> None:
    credential = create_adult_credential(
        subject_id="a",
        issued_at_ms=1_000,
        expires_at_ms=2_000,
    )
    assert adult_credential_is_valid(credential, subject_id="a", now_ms=1_000)
    assert adult_credential_is_valid(credential, subject_id="a", now_ms=1_999)
    assert not adult_credential_is_valid(credential, subject_id="a", now_ms=2_000)
    assert not adult_credential_is_valid(credential, subject_id="b", now_ms=1_500)
    assert not adult_credential_is_valid(
        create_adult_credential(
            subject_id="a",
            issued_at_ms=1_000,
            expires_at_ms=2_000,
            revoked=True,
        ),
        subject_id="a",
        now_ms=1_500,
    )
    with pytest.raises(DomainError, match="credential_timestamp_order"):
        create_adult_credential(subject_id="a", issued_at_ms=2_000, expires_at_ms=2_000)


def test_alignment_uses_reciprocal_weights_and_dealbreakers() -> None:
    left = AlignmentProfile(
        questionnaire_id="v1",
        answers={
            "values": AlignmentAnswer("health", importance=5),
            "structure": AlignmentAnswer("monogamy", importance=5, dealbreaker=True),
        },
    )
    right = AlignmentProfile(
        questionnaire_id="v1",
        answers={
            "values": AlignmentAnswer("health", importance=2),
            "structure": AlignmentAnswer("polyamory", importance=4),
        },
    )
    result = score_alignment(left, right)
    assert result.score_percent == 0
    assert result.dealbreaker_conflict is True
    assert result.matched_weight == 2
    assert result.strongest_matches == ("values",)


def test_alignment_skips_private_prefer_not_and_zero_weight_answers() -> None:
    left = AlignmentProfile(
        questionnaire_id="v1",
        answers={
            "private": AlignmentAnswer("yes", visibility="private_unused"),
            "skip": AlignmentAnswer("prefer_not"),
            "zero": AlignmentAnswer("same", importance=0),
            "kept": AlignmentAnswer("same", importance=4),
        },
    )
    right = AlignmentProfile(
        questionnaire_id="v1",
        answers={key: AlignmentAnswer("same", importance=3) for key in left.answers}
        | {"private": AlignmentAnswer("yes")},
    )
    result = score_alignment(left, right)
    assert result.comparable_questions == 1
    assert result.score_percent == 100


def test_alignment_rejects_version_and_importance_errors() -> None:
    with pytest.raises(DomainError, match="questionnaire_versions_differ"):
        score_alignment(AlignmentProfile("v1", {}), AlignmentProfile("v2", {}))
    with pytest.raises(DomainError, match="importance_out_of_range"):
        score_alignment(
            AlignmentProfile("v1", {"q": AlignmentAnswer("a", importance=6)}),
            AlignmentProfile("v1", {"q": AlignmentAnswer("a")}),
        )


def test_filter_policy_and_intent_compatibility() -> None:
    assert filter_key_allowed("activity_level")
    assert not filter_key_allowed("race")
    assert not filter_key_allowed("inferred_intelligence")
    assert not filter_key_allowed("unknown")
    assert intents_are_compatible(("dating", "gaming"), ("gaming",))
    assert not intents_are_compatible(("dating",), ("conversation",))
