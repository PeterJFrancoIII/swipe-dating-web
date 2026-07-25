"""Reciprocal, explainable, device-local questionnaire alignment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.models import frozen_mapping, js_round


@dataclass(frozen=True, slots=True)
class AlignmentAnswer:
    answer_id: str
    importance: int = 3
    dealbreaker: bool = False
    visibility: str = "score_only"


@dataclass(frozen=True, slots=True)
class AlignmentProfile:
    questionnaire_id: str
    answers: Mapping[str, AlignmentAnswer]

    def __post_init__(self) -> None:
        object.__setattr__(self, "answers", frozen_mapping(self.answers))


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    score_percent: int
    comparable_questions: int
    matched_weight: int
    possible_weight: int
    dealbreaker_conflict: bool
    strongest_matches: tuple[str, ...]
    strongest_differences: tuple[str, ...]


def score_alignment(left: AlignmentProfile, right: AlignmentProfile) -> AlignmentResult:
    if left.questionnaire_id != right.questionnaire_id:
        raise DomainError("questionnaire_versions_differ")

    comparable_questions = 0
    matched_weight = 0
    possible_weight = 0
    matches: list[tuple[str, int]] = []
    differences: list[tuple[str, int]] = []

    for question_id, left_answer in left.answers.items():
        right_answer = right.answers.get(question_id)
        if right_answer is None:
            continue
        _validate_answer(left_answer)
        _validate_answer(right_answer)
        if not _is_comparable(left_answer) or not _is_comparable(right_answer):
            continue

        weight = min(left_answer.importance, right_answer.importance)
        if weight == 0:
            continue
        comparable_questions += 1
        possible_weight += weight
        if left_answer.answer_id == right_answer.answer_id:
            matched_weight += weight
            matches.append((question_id, weight))
        else:
            differences.append((question_id, weight))
            if left_answer.dealbreaker or right_answer.dealbreaker:
                return _result(
                    comparable_questions,
                    matched_weight,
                    possible_weight,
                    True,
                    matches,
                    differences,
                )

    return _result(
        comparable_questions,
        matched_weight,
        possible_weight,
        False,
        matches,
        differences,
    )


def _result(
    comparable_questions: int,
    matched_weight: int,
    possible_weight: int,
    dealbreaker_conflict: bool,
    matches: list[tuple[str, int]],
    differences: list[tuple[str, int]],
) -> AlignmentResult:
    score = (
        0
        if dealbreaker_conflict or possible_weight == 0
        else min(100, js_round(matched_weight * 100 / possible_weight))
    )

    def top(values: list[tuple[str, int]]) -> tuple[str, ...]:
        return tuple(
            question_id
            for question_id, _weight in sorted(values, key=lambda item: (-item[1], item[0]))[:3]
        )

    return AlignmentResult(
        score_percent=score,
        comparable_questions=comparable_questions,
        matched_weight=matched_weight,
        possible_weight=possible_weight,
        dealbreaker_conflict=dealbreaker_conflict,
        strongest_matches=top(matches),
        strongest_differences=top(differences),
    )


def _validate_answer(answer: AlignmentAnswer) -> None:
    if (
        not isinstance(answer.importance, int)
        or isinstance(answer.importance, bool)
        or not 0 <= answer.importance <= 5
    ):
        raise DomainError("importance_out_of_range")


def _is_comparable(answer: AlignmentAnswer) -> bool:
    return (
        answer.visibility != "private_unused"
        and bool(answer.answer_id)
        and answer.answer_id != "prefer_not"
    )
