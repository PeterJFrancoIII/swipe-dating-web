"""Synthetic, content-blind community bot moderation transitions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.models import ValueResult, frozen_mapping, iso_from_ms
from swipe_dating.domain.risk import RiskAction, RiskAssessment

MIN_REVIEWER_ACCOUNT_AGE_DAYS = 90
MIN_MODERATION_REPUTATION = 70
MAX_REPORTS_PER_WINDOW = 5
REVIEW_QUORUM = 7
SUSPICIOUS_VOTES_REQUIRED = 5
WRONG_VOTE_PENALTY = 20
MAX_EVIDENCE_NOTE_LENGTH = 280


class ReportReason(StrEnum):
    AUTOMATION_PATTERN = "automation_pattern"
    COPIED_PROFILE = "copied_profile"
    SUSPICIOUS_LINK = "suspicious_link"
    SCAM = "scam"
    IMPERSONATION = "impersonation"
    STOLEN_PHOTOS = "stolen_photos"
    SPAM_LINKS = "spam_links"
    OTHER_BOT_BEHAVIOR = "other_bot_behavior"
    OTHER_ABUSE = "other_abuse"


class VoteChoice(StrEnum):
    SUSPICIOUS = "suspicious"
    LIKELY_HUMAN = "likely_human"


class CaseStatus(StrEnum):
    OPEN = "open"
    COMMUNITY_REVIEW_COMPLETE = "community_review_complete"
    TEMPORARILY_CONTAINED = "temporarily_contained"
    APPEALED_PENDING_REVIEW = "appealed_pending_review"
    ADJUDICATED_BOT = "adjudicated_bot"
    ADJUDICATED_HUMAN = "adjudicated_human"


@dataclass(frozen=True, slots=True)
class CommunityMember:
    id: str
    adult_eligible: bool
    verified: bool
    account_age_days: int
    good_standing: bool
    moderation_reputation: int = 100
    reports_in_window: int = 0
    trust_cluster_id: str = ""


@dataclass(frozen=True, slots=True)
class BotReport:
    id: str
    reporter_id: str
    subject_profile_id: str
    reason: ReportReason
    created_at: str
    evidence_note: str = ""


@dataclass(frozen=True, slots=True)
class BotVote:
    id: str
    reviewer_id: str
    choice: VoteChoice
    created_at: str


@dataclass(frozen=True, slots=True)
class ModerationCase:
    id: str
    report: BotReport
    risk_score: int
    risk_action: RiskAction
    risk_reasons: tuple[str, ...]
    status: CaseStatus
    contained: bool
    review_complete: bool = False
    votes: tuple[BotVote, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_reasons", tuple(self.risk_reasons))
        object.__setattr__(self, "votes", tuple(self.votes))


@dataclass(frozen=True, slots=True)
class ModerationState:
    members: Mapping[str, CommunityMember]
    cases: Mapping[str, ModerationCase]
    next_case_sequence: int = 1
    next_vote_sequence: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "members", frozen_mapping(self.members))
        object.__setattr__(self, "cases", frozen_mapping(self.cases))


def create_moderation_state(
    members: Iterable[CommunityMember] = (),
) -> ModerationState:
    return ModerationState({member.id: member for member in members}, {})


def file_bot_report(
    state: ModerationState,
    *,
    reporter_id: str,
    subject_profile_id: str,
    reason: ReportReason,
    risk_assessment: RiskAssessment,
    at_ms: int | float,
    evidence_note: str = "",
) -> ValueResult[ModerationState, ModerationCase]:
    reporter = _member(state, reporter_id)
    if not reporter.adult_eligible:
        raise DomainError("reporter_not_adult")
    if not reporter.good_standing:
        raise DomainError("reporter_not_in_good_standing")
    if reporter_id == subject_profile_id:
        raise DomainError("cannot_report_self")
    if not subject_profile_id:
        raise DomainError("report_subject_required")
    if reporter.reports_in_window >= MAX_REPORTS_PER_WINDOW:
        raise DomainError("report_limit_reached")
    if any(
        case.report.subject_profile_id == subject_profile_id
        and case.status
        not in {
            CaseStatus.ADJUDICATED_BOT,
            CaseStatus.ADJUDICATED_HUMAN,
        }
        for case in state.cases.values()
    ):
        raise DomainError("active_bot_case_exists")

    case_id = f"bot-case-{state.next_case_sequence}"
    report = BotReport(
        id=f"bot-report-{state.next_case_sequence}",
        reporter_id=reporter_id,
        subject_profile_id=subject_profile_id,
        reason=reason,
        created_at=iso_from_ms(at_ms),
        evidence_note=_normalize_evidence_note(evidence_note),
    )
    automatically_contained = risk_assessment.action in {
        RiskAction.TEMPORARY_CONTAINMENT,
        RiskAction.DENY,
    }
    case = ModerationCase(
        id=case_id,
        report=report,
        risk_score=risk_assessment.score,
        risk_action=risk_assessment.action,
        risk_reasons=risk_assessment.reasons,
        status=(CaseStatus.TEMPORARILY_CONTAINED if automatically_contained else CaseStatus.OPEN),
        contained=automatically_contained,
    )
    members = dict(state.members)
    members[reporter_id] = replace(
        reporter,
        reports_in_window=reporter.reports_in_window + 1,
    )
    cases = dict(state.cases)
    cases[case_id] = case
    next_state = replace(
        state,
        members=members,
        cases=cases,
        next_case_sequence=state.next_case_sequence + 1,
    )
    return ValueResult(next_state, case)


def cast_bot_vote(
    state: ModerationState,
    *,
    case_id: str,
    reviewer_id: str,
    choice: VoteChoice,
    at_ms: int | float,
) -> ValueResult[ModerationState, ModerationCase]:
    case = _case(state, case_id)
    reviewer = _member(state, reviewer_id)
    if not _reviewer_is_eligible(reviewer):
        raise DomainError("reviewer_not_eligible")
    if reviewer_id == case.report.reporter_id:
        raise DomainError("cannot_vote_on_own_report")
    if reviewer_id == case.report.subject_profile_id:
        raise DomainError("report_subject_cannot_vote")
    if any(vote.reviewer_id == reviewer_id for vote in case.votes):
        raise DomainError("duplicate_bot_vote")
    reviewer_cluster = reviewer.trust_cluster_id
    prior_clusters = {state.members[vote.reviewer_id].trust_cluster_id for vote in case.votes}
    if reviewer_cluster in prior_clusters:
        raise DomainError("reviewer_not_independent")
    if case.review_complete or case.status in {
        CaseStatus.ADJUDICATED_BOT,
        CaseStatus.ADJUDICATED_HUMAN,
    }:
        raise DomainError("case_voting_closed")

    vote = BotVote(
        id=f"bot-vote-{state.next_vote_sequence}",
        reviewer_id=reviewer_id,
        choice=choice,
        created_at=iso_from_ms(at_ms),
    )
    votes = (*case.votes, vote)
    review_complete = len(votes) >= REVIEW_QUORUM
    suspicious_votes = sum(vote.choice is VoteChoice.SUSPICIOUS for vote in votes)
    community_contained = review_complete and suspicious_votes >= SUSPICIOUS_VOTES_REQUIRED
    contained = case.contained or community_contained
    if contained:
        status = CaseStatus.TEMPORARILY_CONTAINED
    elif review_complete:
        status = CaseStatus.COMMUNITY_REVIEW_COMPLETE
    else:
        status = case.status
    updated_case = replace(
        case,
        votes=votes,
        status=status,
        contained=contained,
        review_complete=review_complete,
    )
    cases = dict(state.cases)
    cases[case_id] = updated_case
    next_state = replace(
        state,
        cases=cases,
        next_vote_sequence=state.next_vote_sequence + 1,
    )
    return ValueResult(next_state, updated_case)


def appeal_bot_case(
    state: ModerationState,
    *,
    case_id: str,
    subject_profile_id: str,
) -> ValueResult[ModerationState, ModerationCase]:
    case = _case(state, case_id)
    if case.report.subject_profile_id != subject_profile_id:
        raise DomainError("appeal_subject_mismatch")
    if not case.contained:
        raise DomainError("case_not_contained")
    if case.status in {CaseStatus.ADJUDICATED_BOT, CaseStatus.ADJUDICATED_HUMAN}:
        raise DomainError("case_already_adjudicated")

    updated_case = replace(
        case,
        status=CaseStatus.APPEALED_PENDING_REVIEW,
        review_complete=True,
    )
    cases = dict(state.cases)
    cases[case_id] = updated_case
    next_state = replace(state, cases=cases)
    return ValueResult(next_state, updated_case)


def adjudicate_bot_case(
    state: ModerationState,
    *,
    case_id: str,
    confirmed_bot: bool,
) -> ValueResult[ModerationState, ModerationCase]:
    case = _case(state, case_id)
    if case.status in {CaseStatus.ADJUDICATED_BOT, CaseStatus.ADJUDICATED_HUMAN}:
        raise DomainError("case_already_adjudicated")
    if not case.review_complete and not case.contained:
        raise DomainError("case_not_ready_for_adjudication")

    members = dict(state.members)
    expected_choice = VoteChoice.SUSPICIOUS if confirmed_bot else VoteChoice.LIKELY_HUMAN
    for vote in case.votes:
        if vote.choice is expected_choice:
            continue
        reviewer = members[vote.reviewer_id]
        members[vote.reviewer_id] = replace(
            reviewer,
            moderation_reputation=max(
                0,
                reviewer.moderation_reputation - WRONG_VOTE_PENALTY,
            ),
        )

    updated_case = replace(
        case,
        status=(CaseStatus.ADJUDICATED_BOT if confirmed_bot else CaseStatus.ADJUDICATED_HUMAN),
        contained=confirmed_bot,
        review_complete=True,
    )
    cases = dict(state.cases)
    cases[case_id] = updated_case
    next_state = replace(state, members=members, cases=cases)
    return ValueResult(next_state, updated_case)


def contained_profile_ids(state: ModerationState) -> tuple[str, ...]:
    return tuple(
        sorted({case.report.subject_profile_id for case in state.cases.values() if case.contained})
    )


def get_moderation_case(state: ModerationState, case_id: str) -> ModerationCase:
    return _case(state, case_id)


def eligible_reviewer_ids(
    state: ModerationState,
    case_id: str,
) -> tuple[str, ...]:
    case = _case(state, case_id)
    if case.review_complete:
        return ()
    voter_ids = {vote.reviewer_id for vote in case.votes}
    used_clusters = {state.members[vote.reviewer_id].trust_cluster_id for vote in case.votes}
    return tuple(
        sorted(
            member.id
            for member in state.members.values()
            if _reviewer_is_eligible(member)
            and member.id
            not in {
                case.report.reporter_id,
                case.report.subject_profile_id,
                *voter_ids,
            }
            and member.trust_cluster_id not in used_clusters
        )
    )


def _member(state: ModerationState, member_id: str) -> CommunityMember:
    try:
        return state.members[member_id]
    except KeyError as error:
        raise DomainError("moderation_member_unknown") from error


def _case(state: ModerationState, case_id: str) -> ModerationCase:
    try:
        return state.cases[case_id]
    except KeyError as error:
        raise DomainError("moderation_case_unknown") from error


def _reviewer_is_eligible(reviewer: CommunityMember) -> bool:
    return bool(
        reviewer.adult_eligible
        and reviewer.verified
        and reviewer.account_age_days >= MIN_REVIEWER_ACCOUNT_AGE_DAYS
        and reviewer.good_standing
        and reviewer.moderation_reputation >= MIN_MODERATION_REPUTATION
        and bool(reviewer.trust_cluster_id)
    )


def _normalize_evidence_note(value: str) -> str:
    return value.strip()[:MAX_EVIDENCE_NOTE_LENGTH] if isinstance(value, str) else ""
