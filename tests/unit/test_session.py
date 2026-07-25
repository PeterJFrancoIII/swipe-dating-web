from __future__ import annotations

import json
from dataclasses import replace

import pytest

from swipe_dating.adapters.storage import LocalStateRepository, MemoryStorageAdapter
from swipe_dating.application.session import ResearchSession
from swipe_dating.domain.bot_moderation import CaseStatus, ReportReason, VoteChoice
from swipe_dating.domain.conversations import MatchStatus
from swipe_dating.domain.discovery import DiscoveryProfile
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.risk import RiskAction
from swipe_dating.fixtures import SYNTHETIC_PROFILES

NOW = 1_753_185_600_000


def create_session(
    profiles: tuple[DiscoveryProfile, ...] = SYNTHETIC_PROFILES,
) -> tuple[ResearchSession, MemoryStorageAdapter]:
    adapter = MemoryStorageAdapter()
    session = ResearchSession(
        repository=LocalStateRepository(adapter),
        clock=lambda: NOW,
        today="2026-07-22",
        profiles=profiles,
    )
    return session, adapter


def test_adult_gate_opens_directly_onto_a_swipe_card() -> None:
    session, _adapter = create_session()
    with pytest.raises(DomainError, match="birth_date_invalid"):
        session.accept_adult_gate("01/01/2000")
    with pytest.raises(DomainError, match="adult_only"):
        session.accept_adult_gate("2009-07-22")
    assert session.adult_accepted is False
    session.accept_adult_gate("  2000-01-01  ")
    assert session.adult_accepted is True
    assert session.birth_date == "2000-01-01"

    current = session.current_candidate()
    assert current is not None and current.candidate.id == "p1"


def test_crowd_bot_review_contains_then_restores_a_synthetic_human() -> None:
    session, adapter = create_session()
    session.accept_adult_gate("2000-01-01")

    case = session.report_suspected_bot("p1", ReportReason.AUTOMATION_PATTERN)
    session.vote_on_bot_case(case.id, "reviewer-ava", VoteChoice.SUSPICIOUS)
    session.vote_on_bot_case(case.id, "reviewer-noah", VoteChoice.LIKELY_HUMAN)
    contained = session.vote_on_bot_case(
        case.id,
        "reviewer-sam",
        VoteChoice.SUSPICIOUS,
    )

    assert contained.status is CaseStatus.TEMPORARILY_CONTAINED
    assert all(item.candidate.id != "p1" for item in session.discovery_queue())
    session.appeal_bot_containment(case.id)
    adjudicated = session.run_synthetic_adjudication(case.id)
    assert adjudicated.status is CaseStatus.ADJUDICATED_HUMAN
    assert any(item.candidate.id == "p1" for item in session.discovery_queue())
    assert session.moderation_state.members["reviewer-ava"].moderation_reputation == 80
    assert adapter.inspect() is None


def test_automated_bot_risk_contains_and_blocks_stale_interest() -> None:
    session, _adapter = create_session()
    with pytest.raises(DomainError, match="adult_gate_required"):
        session.report_suspected_bot("p2", ReportReason.SUSPICIOUS_LINK)
    session.accept_adult_gate("2000-01-01")

    case = session.report_suspected_bot("p2", ReportReason.SUSPICIOUS_LINK)

    assert case.status is CaseStatus.TEMPORARILY_CONTAINED
    assert {reviewer.id for reviewer in session.eligible_reviewers(case.id)} == {
        "reviewer-ava",
        "reviewer-noah",
        "reviewer-sam",
    }
    assert all(item.candidate.id != "p2" for item in session.discovery_queue())
    with pytest.raises(DomainError, match="candidate_temporarily_contained"):
        session.express_interest("p2")


def test_missing_bot_risk_evidence_fails_closed() -> None:
    unknown = replace(SYNTHETIC_PROFILES[0], id="profile-without-risk-fixture")
    session, _adapter = create_session((unknown,))
    session.accept_adult_gate("2000-01-01")

    case = session.report_suspected_bot(
        unknown.id,
        ReportReason.AUTOMATION_PATTERN,
    )

    assert case.risk_action is RiskAction.DENY
    assert case.risk_reasons == ("adult_credential_invalid",)
    assert case.contained is True


def test_match_message_and_unmatch_are_coordinated_in_memory() -> None:
    session, adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    outcome = session.express_interest("p1")
    assert outcome["matched"] is True
    assert session.active_tab == "Matches"
    match_id = str(outcome["match_id"])

    message = session.send_message(match_id, "What trail do you like?")
    assert message.shared_ground_tag is None
    assert session.receive_synthetic_reply(match_id, "I like the river loop.").sender == "candidate"

    ended = session.unmatch(match_id)
    assert ended["kind"] == "unmatched"
    assert session.conversations.matches[match_id].status is MatchStatus.UNMATCHED

    # Session-only adult, discovery, match, and message state never reaches storage.
    assert adapter.inspect() is None


def test_meetup_proposal_is_session_only_and_purged_on_block() -> None:
    session, adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    outcome = session.express_interest("p1")
    match_id = str(outcome["match_id"])
    session.send_message(match_id, "What trail do you like?")
    session.receive_synthetic_reply(match_id, "I like the river loop.")

    proposal = session.propose_meetup(match_id, "coffee_public")

    assert "public place" in proposal.body
    assert adapter.inspect() is None
    session.block(match_id)
    assert session.conversations.matches[match_id].messages == ()


def test_block_purges_content_and_suppresses_candidate() -> None:
    session, _adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    outcome = session.express_interest("p1")
    match_id = str(outcome["match_id"])
    session.send_message(match_id, "Opening")
    session.block(match_id)
    match = session.conversations.matches[match_id]
    assert match.status is MatchStatus.BLOCKED
    assert match.content_purged and not match.messages and match.starter_tag is None
    assert all(entry.candidate.id != "p1" for entry in session.discovery_queue())


def test_only_allowlisted_profile_cosmetic_and_safe_tab_state_persists() -> None:
    session, adapter = create_session()
    session.update_profile(display_name="Riley", about="Builder", pronouns="they/them")
    session.select_tab("Swipe")
    session.acquire_or_apply_skin("neon-orbit")
    session.select_tab("Matches")
    session.selected_intents.add("casual_sex")
    session.questionnaire_answers["politics"] = "private"
    session.location_choice = "live_15_minutes"

    raw = json.loads(adapter.inspect())
    assert raw["profile"]["displayName"] == "Riley"
    assert raw["cosmetics"]["selectedSkinId"] == "neon-orbit"
    assert raw["ui"]["lastTab"] == "Swipe"
    assert set(raw) == {"schemaVersion", "savedAt", "profile", "cosmetics", "ui"}


def test_unknown_tab_is_rejected() -> None:
    session, _adapter = create_session()
    with pytest.raises(DomainError, match="unknown_tab"):
        session.select_tab("Skin Shop")


def test_profile_readiness_is_derived_and_never_persisted() -> None:
    session, adapter = create_session()
    session.update_profile(display_name="Riley", about="x" * 80, pronouns="")

    readiness = session.profile_readiness()

    assert readiness.ready is True
    raw = json.loads(adapter.inspect())
    assert "readiness" not in raw
    assert set(raw["profile"]) == {"displayName", "about", "pronouns"}


def test_pass_undo_restores_candidate() -> None:
    session, _adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    assert session.pass_candidate("p1")["kind"] == "passed"
    assert session.current_candidate().candidate.id == "p3"  # type: ignore[union-attr]
    outcome = session.undo_last_decision()
    assert outcome["restored_candidate_id"] == "p1"
    assert session.active_tab == "Swipe"
    assert session.current_candidate().candidate.id == "p1"  # type: ignore[union-attr]
