from __future__ import annotations

import pytest

from swipe_dating.domain.bot_moderation import (
    CaseStatus,
    CommunityMember,
    ReportReason,
    VoteChoice,
    adjudicate_bot_case,
    appeal_bot_case,
    cast_bot_vote,
    contained_profile_ids,
    create_moderation_state,
    file_bot_report,
)
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.risk import RiskAction, RiskAssessment

NOW = 1_700_000_000_000


def member(member_id: str, **overrides: object) -> CommunityMember:
    values: dict[str, object] = {
        "id": member_id,
        "adult_eligible": True,
        "verified": True,
        "account_age_days": 365,
        "good_standing": True,
        "moderation_reputation": 100,
        "trust_cluster_id": f"cluster-{member_id}",
    }
    values.update(overrides)
    return CommunityMember(**values)  # type: ignore[arg-type]


def low_risk() -> RiskAssessment:
    return RiskAssessment(0, RiskAction.ALLOW, ())


def panel() -> tuple[CommunityMember, ...]:
    return (
        member("reporter"),
        *(member(f"reviewer-{index}") for index in range(1, 8)),
        member("candidate"),
    )


def reported_state():  # type: ignore[no-untyped-def]
    return file_bot_report(
        create_moderation_state(panel()),
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.AUTOMATION_PATTERN,
        risk_assessment=low_risk(),
        evidence_note="Profile sent the same suspicious pitch repeatedly.",
        at_ms=NOW,
    )


def test_adult_user_can_open_report_with_short_evidence_note() -> None:
    result = reported_state()
    assert result.value.id == "bot-case-1"
    assert result.value.report.evidence_note.startswith("Profile sent")
    assert result.state.members["reporter"].reports_in_window == 1


def test_evidence_note_is_bounded() -> None:
    result = file_bot_report(
        create_moderation_state((member("reporter"),)),
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.OTHER_ABUSE,
        risk_assessment=low_risk(),
        evidence_note="x" * 500,
        at_ms=NOW,
    )
    assert len(result.value.report.evidence_note) == 280


@pytest.mark.parametrize(
    "overrides",
    [
        {"adult_eligible": False},
        {"verified": False},
        {"account_age_days": 89},
        {"good_standing": False},
        {"moderation_reputation": 69},
        {"trust_cluster_id": ""},
    ],
)
def test_only_eligible_90_day_members_can_vote(overrides: dict[str, object]) -> None:
    state = create_moderation_state((member("reporter"), member("reviewer", **overrides)))
    reported = file_bot_report(
        state,
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.SCAM,
        risk_assessment=low_risk(),
        at_ms=NOW,
    )
    with pytest.raises(DomainError, match="reviewer_not_eligible"):
        cast_bot_vote(
            reported.state,
            case_id=reported.value.id,
            reviewer_id="reviewer",
            choice=VoteChoice.SUSPICIOUS,
            at_ms=NOW + 1,
        )


def test_five_of_seven_independent_votes_temporarily_contain_profile() -> None:
    reported = reported_state()
    state = reported.state
    choices = (
        VoteChoice.SUSPICIOUS,
        VoteChoice.SUSPICIOUS,
        VoteChoice.LIKELY_HUMAN,
        VoteChoice.SUSPICIOUS,
        VoteChoice.SUSPICIOUS,
        VoteChoice.LIKELY_HUMAN,
        VoteChoice.SUSPICIOUS,
    )
    for index, choice in enumerate(choices, start=1):
        voted = cast_bot_vote(
            state,
            case_id=reported.value.id,
            reviewer_id=f"reviewer-{index}",
            choice=choice,
            at_ms=NOW + index,
        )
        state = voted.state

    assert voted.value.review_complete is True
    assert voted.value.contained is True
    assert voted.value.status is CaseStatus.TEMPORARILY_CONTAINED
    assert len(voted.value.votes) == 7


def test_four_of_seven_finishes_review_without_community_containment() -> None:
    reported = reported_state()
    state = reported.state
    choices = (
        VoteChoice.SUSPICIOUS,
        VoteChoice.SUSPICIOUS,
        VoteChoice.SUSPICIOUS,
        VoteChoice.SUSPICIOUS,
        VoteChoice.LIKELY_HUMAN,
        VoteChoice.LIKELY_HUMAN,
        VoteChoice.LIKELY_HUMAN,
    )
    for index, choice in enumerate(choices, start=1):
        voted = cast_bot_vote(
            state,
            case_id=reported.value.id,
            reviewer_id=f"reviewer-{index}",
            choice=choice,
            at_ms=NOW + index,
        )
        state = voted.state
    assert voted.value.review_complete is True
    assert voted.value.contained is False
    assert voted.value.status is CaseStatus.COMMUNITY_REVIEW_COMPLETE


def test_automated_high_risk_can_temporarily_contain_pending_review() -> None:
    high_risk = RiskAssessment(85, RiskAction.TEMPORARY_CONTAINMENT, ("automated_liking",))
    result = file_bot_report(
        create_moderation_state((member("reporter"),)),
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.SPAM_LINKS,
        risk_assessment=high_risk,
        at_ms=NOW,
    )
    assert result.value.contained is True
    assert result.value.review_complete is False
    assert result.value.status is CaseStatus.TEMPORARILY_CONTAINED


def test_report_limits_duplicate_cases_and_duplicate_votes_fail_closed() -> None:
    limited = member("limited", reports_in_window=5)
    with pytest.raises(DomainError, match="report_limit_reached"):
        file_bot_report(
            create_moderation_state((limited,)),
            reporter_id="limited",
            subject_profile_id="candidate",
            reason=ReportReason.OTHER_ABUSE,
            risk_assessment=low_risk(),
            at_ms=NOW,
        )

    first = reported_state()
    with pytest.raises(DomainError, match="active_bot_case_exists"):
        file_bot_report(
            first.state,
            reporter_id="reporter",
            subject_profile_id="candidate",
            reason=ReportReason.IMPERSONATION,
            risk_assessment=low_risk(),
            at_ms=NOW + 1,
        )

    voted = cast_bot_vote(
        first.state,
        case_id=first.value.id,
        reviewer_id="reviewer-1",
        choice=VoteChoice.SUSPICIOUS,
        at_ms=NOW + 1,
    )
    with pytest.raises(DomainError, match="duplicate_bot_vote"):
        cast_bot_vote(
            voted.state,
            case_id=first.value.id,
            reviewer_id="reviewer-1",
            choice=VoteChoice.LIKELY_HUMAN,
            at_ms=NOW + 2,
        )


def test_review_quorum_requires_independent_trust_clusters() -> None:
    state = create_moderation_state(
        (
            member("reporter"),
            member("reviewer-1", trust_cluster_id="shared-device"),
            member("reviewer-2", trust_cluster_id="shared-device"),
        )
    )
    reported = file_bot_report(
        state,
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.SCAM,
        risk_assessment=low_risk(),
        at_ms=NOW,
    )
    voted = cast_bot_vote(
        reported.state,
        case_id=reported.value.id,
        reviewer_id="reviewer-1",
        choice=VoteChoice.SUSPICIOUS,
        at_ms=NOW + 1,
    )
    with pytest.raises(DomainError, match="reviewer_not_independent"):
        cast_bot_vote(
            voted.state,
            case_id=reported.value.id,
            reviewer_id="reviewer-2",
            choice=VoteChoice.SUSPICIOUS,
            at_ms=NOW + 2,
        )


def test_appeal_and_adjudication_restore_human_and_penalize_wrong_votes() -> None:
    reported = reported_state()
    state = reported.state
    for index in range(1, 8):
        choice = VoteChoice.SUSPICIOUS if index <= 5 else VoteChoice.LIKELY_HUMAN
        state = cast_bot_vote(
            state,
            case_id=reported.value.id,
            reviewer_id=f"reviewer-{index}",
            choice=choice,
            at_ms=NOW + index,
        ).state

    appealed = appeal_bot_case(state, case_id=reported.value.id, subject_profile_id="candidate")
    assert appealed.value.status is CaseStatus.APPEALED_PENDING_REVIEW
    assert contained_profile_ids(appealed.state) == ("candidate",)

    adjudicated = adjudicate_bot_case(
        appealed.state,
        case_id=reported.value.id,
        confirmed_bot=False,
    )
    assert adjudicated.value.status is CaseStatus.ADJUDICATED_HUMAN
    assert adjudicated.value.contained is False
    assert contained_profile_ids(adjudicated.state) == ()
    assert adjudicated.state.members["reviewer-1"].moderation_reputation == 80
    assert adjudicated.state.members["reviewer-6"].moderation_reputation == 100
