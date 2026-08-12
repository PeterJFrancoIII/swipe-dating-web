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

    case = session.report_suspected_bot(
        "p1",
        ReportReason.AUTOMATION_PATTERN,
        evidence_note="Synthetic review evidence",
    )
    choices = (
        VoteChoice.SUSPICIOUS,
        VoteChoice.SUSPICIOUS,
        VoteChoice.LIKELY_HUMAN,
        VoteChoice.SUSPICIOUS,
        VoteChoice.SUSPICIOUS,
        VoteChoice.LIKELY_HUMAN,
        VoteChoice.SUSPICIOUS,
    )
    contained = case
    for index, choice in enumerate(choices, start=1):
        contained = session.vote_on_bot_case(case.id, f"reviewer-{index}", choice)

    assert contained.status is CaseStatus.TEMPORARILY_CONTAINED
    assert all(item.candidate.id != "p1" for item in session.discovery_queue())
    session.appeal_bot_containment(case.id)
    adjudicated = session.run_synthetic_adjudication(case.id)
    assert adjudicated.status is CaseStatus.ADJUDICATED_HUMAN
    assert any(item.candidate.id == "p1" for item in session.discovery_queue())
    assert session.moderation_state.members["reviewer-1"].moderation_reputation == 80
    assert adapter.inspect() is None


def test_automated_bot_risk_contains_and_blocks_stale_interest() -> None:
    session, _adapter = create_session()
    with pytest.raises(DomainError, match="adult_gate_required"):
        session.report_suspected_bot("p2", ReportReason.SUSPICIOUS_LINK)
    session.accept_adult_gate("2000-01-01")

    case = session.report_suspected_bot("p2", ReportReason.SUSPICIOUS_LINK)
    assert case.status is CaseStatus.TEMPORARILY_CONTAINED
    assert {reviewer.id for reviewer in session.eligible_reviewers(case.id)} == {
        f"reviewer-{index}" for index in range(1, 8)
    }
    assert all(item.candidate.id != "p2" for item in session.discovery_queue())
    with pytest.raises(DomainError, match="candidate_temporarily_contained"):
        session.express_interest("p2")


def test_missing_bot_risk_evidence_fails_closed() -> None:
    unknown = replace(SYNTHETIC_PROFILES[0], id="profile-without-risk-fixture")
    session, _adapter = create_session((unknown,))
    session.accept_adult_gate("2000-01-01")
    case = session.report_suspected_bot(unknown.id, ReportReason.AUTOMATION_PATTERN)
    assert case.risk_action is RiskAction.DENY
    assert case.risk_reasons == ("adult_credential_invalid",)
    assert case.contained is True


def test_match_message_meetup_extension_and_unmatch_are_session_only() -> None:
    session, adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    outcome = session.express_interest("p1")
    assert outcome["matched"] is True
    assert session.active_tab == "Matches"
    match_id = str(outcome["match_id"])
    assert session.active_matches()[0].id == match_id
    assert session.meetup_suggestions(match_id)[0].id == "coffee_public"

    proposal = session.propose_meetup(match_id, "coffee_public")
    assert "public place" in proposal.body
    for index in range(19):
        session.send_message(match_id, f"message {index}")
    with pytest.raises(DomainError, match="message_limit_reached"):
        session.send_message(match_id, "blocked by initial limit")
    assert session.extend_messages(match_id)["kind"] == "message_limit_extended"
    assert session.send_message(match_id, "after extension").body == "after extension"

    ended = session.unmatch(match_id)
    assert ended["kind"] == "unmatched"
    assert session.conversations.matches[match_id].status is MatchStatus.UNMATCHED
    assert adapter.inspect() is None


def test_synthetic_reply_and_block_purge_visible_content() -> None:
    session, adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    outcome = session.express_interest("p1")
    match_id = str(outcome["match_id"])
    session.send_message(match_id, "What trail do you like?")
    assert session.receive_synthetic_reply(match_id, "I like the river loop.").sender == "candidate"
    blocked = session.block(match_id)
    assert blocked["kind"] == "blocked"
    match = session.conversations.matches[match_id]
    assert match.status is MatchStatus.BLOCKED
    assert match.content_purged and not match.messages and match.starter_tag is None
    assert all(entry.candidate.id != "p1" for entry in session.discovery_queue())
    assert adapter.inspect() is None


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


def test_preferences_change_eligibility_without_exposing_weight_controls() -> None:
    session, _adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    session.update_preferences(
        immediate_intent="casual_dating",
        relational_openness="open_to_more",
        required_boundaries=("public_first_meet",),
    )
    viewer = session.viewer()
    assert viewer.required_boundaries == ("public_first_meet",)
    assert session.current_candidate() is not None


def test_unknown_tab_skin_candidate_and_match_are_rejected() -> None:
    session, _adapter = create_session()
    with pytest.raises(DomainError, match="unknown_tab"):
        session.select_tab("Skin Shop")
    with pytest.raises(DomainError, match="unknown_skin"):
        session.acquire_or_apply_skin("not-real")
    with pytest.raises(DomainError, match="candidate_not_found"):
        session.candidate_profile("not-real")
    with pytest.raises(DomainError, match="match_not_found"):
        session.match("match:none")


def test_profile_readiness_reset_export_and_haptics_use_safe_storage() -> None:
    session, adapter = create_session()
    session.update_profile(display_name="Riley", about="x" * 80, pronouns="")
    readiness = session.profile_readiness()
    assert readiness.ready is True
    session.set_haptics(False)
    exported = session.export_saved_profile()
    assert '"displayName":"Riley"' in exported
    raw = json.loads(adapter.inspect())
    assert "readiness" not in raw
    assert set(raw["profile"]) == {"displayName", "about", "pronouns"}
    reset = session.reset_saved_profile()
    assert reset.profile.display_name == ""
    assert session.active_tab == "Swipe"


def test_pass_undo_restores_candidate() -> None:
    session, _adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    assert session.pass_candidate("p1")["kind"] == "passed"
    current = session.current_candidate()
    assert current is not None and current.candidate.id != "p1"
    outcome = session.undo_last_decision()
    assert outcome["restored_candidate_id"] == "p1"
    assert session.active_tab == "Swipe"
    assert session.current_candidate().candidate.id == "p1"  # type: ignore[union-attr]
