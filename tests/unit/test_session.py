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
from swipe_dating.domain.preferences import visibility_from_form
from swipe_dating.domain.risk import RiskAction
from swipe_dating.fixtures import SYNTHETIC_PROFILES

NOW = 1_753_185_600_000
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
    assert set(raw["profile"]) == {
        "displayName",
        "about",
        "pronouns",
        "genderIdentities",
        "photoId",
        "lifestyleTags",
        "hobbyTags",
        "personalityTags",
        "bedroomTags",
        "cardVisibility",
    }
    reset = session.reset_saved_profile()
    assert reset.profile.display_name == ""
    assert session.active_tab == "Swipe"


def test_profile_photos_stay_in_session_memory_not_local_state() -> None:
    session, adapter = create_session()
    with pytest.raises(DomainError, match="adult_gate_required"):
        session.set_profile_photo(0, PNG_1X1)
    session.accept_adult_gate("2000-01-01")
    stored = session.set_profile_photo(0, PNG_1X1)
    assert stored.content_type == "image/heic"
    assert stored.display_content_type == "image/avif"
    assert session.filled_photo_count() == 1
    assert session.first_profile_photo_slot() == 0
    assert session.profile_photo_at(0) is stored
    assert session.profile_photo_at(9) is None
    session.update_profile(display_name="Riley", about="Climbing.", pronouns="")
    persisted = adapter.inspect() or ""
    assert "profilePhotos" not in persisted
    assert PNG_1X1 not in persisted.encode("utf-8")
    session.clear_profile_photo(0)
    assert session.profile_photo_at(0) is None
    session.set_profile_photo(5, PNG_1X1)
    assert session.filled_photo_count() == 1
    assert session.profile_photo_at(0) is not None
    session.move_profile_photo(0, "down")
    session.reset_saved_profile()
    assert session.filled_photo_count() == 0
    assert session.first_profile_photo_slot() is None
    assert session.share_token is None


def test_profile_photos_can_be_reordered() -> None:
    session, _adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    first = session.set_profile_photo(0, PNG_1X1)
    second = session.set_profile_photo(1, PNG_1X1)
    session.move_profile_photo(0, "down")
    assert session.profile_photo_at(0) is second
    assert session.profile_photo_at(1) is first
    session.move_profile_photo(1, "up")
    assert session.profile_photo_at(0) is first
    assert session.profile_photo_at(1) is second
    session.move_profile_photo(0, "up")
    assert session.profile_photo_at(0) is first
    session.reorder_profile_photos((1, 0))
    assert session.profile_photo_at(0) is second
    assert session.profile_photo_at(1) is first
    session.reorder_profile_photos((1, 0))
    assert session.profile_photo_at(0) is first
    with pytest.raises(DomainError, match="photo_slot_invalid"):
        session.move_profile_photo(5, "down")
    with pytest.raises(DomainError, match="photo_move_invalid"):
        session.move_profile_photo(0, "sideways")
    with pytest.raises(DomainError, match="photo_order_invalid"):
        session.reorder_profile_photos((0,))
    with pytest.raises(DomainError, match="photo_order_invalid"):
        session.reorder_profile_photos((0, 0))
    token = session.ensure_share_token()
    assert session.ensure_share_token() == token
    session.reset_saved_profile()
    assert session.share_token is None


def test_profile_photo_slots_fill_then_reject_another() -> None:
    session, _adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    for _index in range(6):
        session.add_profile_photo(PNG_1X1)
    assert session.next_empty_photo_slot() is None
    with pytest.raises(DomainError, match="photo_slots_full"):
        session.add_profile_photo(PNG_1X1)


def test_saved_profile_fields_populate_the_viewer_card() -> None:
    session, _adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    session.update_profile(
        display_name="Taylor",
        about="Climbing and films.",
        pronouns="they/them",
        gender_identities=("non_binary", "agender"),
        photo_id="p3",
        lifestyle_tags=("movie_night",),
        hobby_tags=("climbing",),
        personality_tags=("calm",),
        feed_genders=("woman", "man", "non_binary"),
    )
    viewer = session.viewer()
    assert session.profile_age() == 26
    assert viewer.display_name == "Taylor"
    assert viewer.about == "Climbing and films."
    assert viewer.lifestyle_tags == ("movie_night", "climbing", "calm")
    assert session.local_state.profile.photo_id == "p3"
    assert session.local_state.profile.gender_identities == ("non_binary", "agender")
    assert session.selected_genders == {"woman", "man", "non_binary"}
    exported = json.loads(session.export_saved_profile())
    assert exported["profile"]["genderIdentities"] == ["non_binary", "agender"]
    assert "showGenders" not in exported["profile"]
    assert "selectedGenders" not in exported


def test_bedroom_tags_and_card_visibility_persist_without_feed_leak() -> None:
    session, _adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    session.update_profile(
        display_name="Taylor",
        about="Climbing and films.",
        pronouns="they/them",
        lifestyle_tags=("coffee",),
        bedroom_tags=("bdsm", "vanilla"),
        visibility=visibility_from_form(("bedroom", "interests"), present=True),
        feed_genders=("woman",),
    )
    profile = session.local_state.profile
    assert profile.bedroom_tags == ("bdsm", "vanilla")
    assert profile.visibility.bedroom is True
    assert profile.visibility.about is False
    assert profile.visibility.interests is True
    viewer = session.viewer()
    assert viewer.lifestyle_tags == ("coffee",)
    assert "bdsm" not in viewer.lifestyle_tags
    exported = json.loads(session.export_saved_profile())
    assert exported["profile"]["bedroomTags"] == ["bdsm", "vanilla"]
    assert exported["profile"]["cardVisibility"]["bedroom"] is True
    assert exported["profile"]["cardVisibility"]["about"] is False
    assert "selectedGenders" not in exported
    assert "showGenders" not in exported["profile"]


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
