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


def test_adult_user_can_open_a_synthetic_bot_report() -> None:
    state = create_moderation_state((member("reporter"), member("reviewer")))

    result = file_bot_report(
        state,
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.AUTOMATION_PATTERN,
        risk_assessment=low_risk(),
        at_ms=NOW,
    )

    assert result.value.id == "bot-case-1"
    assert result.value.report.reporter_id == "reporter"
    assert result.value.report.subject_profile_id == "candidate"
    assert result.value.contained is False
    assert result.state.members["reporter"].reports_in_window == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"adult_eligible": False},
        {"verified": False},
        {"account_age_days": 179},
        {"good_standing": False},
        {"moderation_reputation": 69},
        {"trust_cluster_id": ""},
    ],
)
def test_only_long_standing_verified_reputable_members_can_vote(
    overrides: dict[str, object],
) -> None:
    state = create_moderation_state((member("reporter"), member("reviewer", **overrides)))
    reported = file_bot_report(
        state,
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.AUTOMATION_PATTERN,
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


def test_two_of_three_trusted_votes_temporarily_contain_a_profile() -> None:
    members = (
        member("reporter"),
        member("reviewer-1"),
        member("reviewer-2"),
        member("reviewer-3"),
    )
    reported = file_bot_report(
        create_moderation_state(members),
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.AUTOMATION_PATTERN,
        risk_assessment=low_risk(),
        at_ms=NOW,
    )

    state = reported.state
    for offset, (reviewer_id, choice) in enumerate(
        (
            ("reviewer-1", VoteChoice.SUSPICIOUS),
            ("reviewer-2", VoteChoice.LIKELY_HUMAN),
            ("reviewer-3", VoteChoice.SUSPICIOUS),
        ),
        start=1,
    ):
        voted = cast_bot_vote(
            state,
            case_id=reported.value.id,
            reviewer_id=reviewer_id,
            choice=choice,
            at_ms=NOW + offset,
        )
        state = voted.state

    assert voted.value.review_complete is True
    assert voted.value.contained is True
    assert voted.value.status is CaseStatus.TEMPORARILY_CONTAINED


def test_automated_high_risk_independently_contains_pending_review() -> None:
    high_risk = RiskAssessment(
        85,
        RiskAction.TEMPORARY_CONTAINMENT,
        ("automated_liking", "profile_scraping"),
    )

    result = file_bot_report(
        create_moderation_state((member("reporter"),)),
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.AUTOMATION_PATTERN,
        risk_assessment=high_risk,
        at_ms=NOW,
    )

    assert result.value.contained is True
    assert result.value.review_complete is False
    assert result.value.status is CaseStatus.TEMPORARILY_CONTAINED
    assert result.value.risk_reasons == ("automated_liking", "profile_scraping")


def test_report_limits_and_duplicate_votes_fail_closed() -> None:
    limited = member("limited", reports_in_window=5)
    with pytest.raises(DomainError, match="report_limit_reached"):
        file_bot_report(
            create_moderation_state((limited,)),
            reporter_id="limited",
            subject_profile_id="candidate",
            reason=ReportReason.OTHER_BOT_BEHAVIOR,
            risk_assessment=low_risk(),
            at_ms=NOW,
        )

    reported = file_bot_report(
        create_moderation_state((member("reporter"), member("reviewer"))),
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.OTHER_BOT_BEHAVIOR,
        risk_assessment=low_risk(),
        at_ms=NOW,
    )
    voted = cast_bot_vote(
        reported.state,
        case_id=reported.value.id,
        reviewer_id="reviewer",
        choice=VoteChoice.SUSPICIOUS,
        at_ms=NOW + 1,
    )
    with pytest.raises(DomainError, match="duplicate_bot_vote"):
        cast_bot_vote(
            voted.state,
            case_id=reported.value.id,
            reviewer_id="reviewer",
            choice=VoteChoice.LIKELY_HUMAN,
            at_ms=NOW + 2,
        )


def test_only_one_active_case_can_exist_per_profile() -> None:
    state = create_moderation_state((member("reporter-1"), member("reporter-2")))
    first = file_bot_report(
        state,
        reporter_id="reporter-1",
        subject_profile_id="candidate",
        reason=ReportReason.AUTOMATION_PATTERN,
        risk_assessment=low_risk(),
        at_ms=NOW,
    )

    with pytest.raises(DomainError, match="active_bot_case_exists"):
        file_bot_report(
            first.state,
            reporter_id="reporter-2",
            subject_profile_id="candidate",
            reason=ReportReason.COPIED_PROFILE,
            risk_assessment=low_risk(),
            at_ms=NOW + 1,
        )


def test_review_quorum_requires_independent_trust_clusters() -> None:
    reported = file_bot_report(
        create_moderation_state(
            (
                member("reporter"),
                member("reviewer-1", trust_cluster_id="shared-device"),
                member("reviewer-2", trust_cluster_id="shared-device"),
            )
        ),
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.AUTOMATION_PATTERN,
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


def test_appeal_and_synthetic_adjudication_restore_human_and_penalize_wrong_votes() -> None:
    members = (
        member("reporter"),
        member("reviewer-1", moderation_reputation=75),
        member("reviewer-2"),
        member("reviewer-3"),
        member("candidate"),
    )
    reported = file_bot_report(
        create_moderation_state(members),
        reporter_id="reporter",
        subject_profile_id="candidate",
        reason=ReportReason.AUTOMATION_PATTERN,
        risk_assessment=low_risk(),
        at_ms=NOW,
    )
    state = reported.state
    for offset, (reviewer_id, choice) in enumerate(
        (
            ("reviewer-1", VoteChoice.SUSPICIOUS),
            ("reviewer-2", VoteChoice.LIKELY_HUMAN),
            ("reviewer-3", VoteChoice.SUSPICIOUS),
        ),
        start=1,
    ):
        voted = cast_bot_vote(
            state,
            case_id=reported.value.id,
            reviewer_id=reviewer_id,
            choice=choice,
            at_ms=NOW + offset,
        )
        state = voted.state

    appealed = appeal_bot_case(
        state,
        case_id=reported.value.id,
        subject_profile_id="candidate",
    )
    assert appealed.value.status is CaseStatus.APPEALED_PENDING_REVIEW
    assert appealed.value.contained is True
    assert contained_profile_ids(appealed.state) == ("candidate",)

    adjudicated = adjudicate_bot_case(
        appealed.state,
        case_id=reported.value.id,
        confirmed_bot=False,
    )

    assert adjudicated.value.status is CaseStatus.ADJUDICATED_HUMAN
    assert adjudicated.value.contained is False
    assert contained_profile_ids(adjudicated.state) == ()
    assert adjudicated.state.members["reviewer-1"].moderation_reputation == 55
    assert adjudicated.state.members["reviewer-2"].moderation_reputation == 100
    assert adjudicated.state.members["reviewer-3"].moderation_reputation == 80
