from __future__ import annotations

import pytest

from swipe_dating.domain.conversations import (
    INITIAL_MESSAGE_LIMIT,
    CandidateSnapshot,
    MatchStatus,
    block_conversation,
    build_meetup_suggestions,
    build_starter_suggestions,
    create_conversation_state,
    extend_conversation,
    get_suppressed_candidate_ids,
    receive_synthetic_reply,
    record_interest,
    record_pass,
    send_meetup_proposal,
    send_message,
    undo_last_decision,
    unmatch_conversation,
)
from swipe_dating.domain.errors import DomainError

CANDIDATE = CandidateSnapshot(id="p1", display_name="Alex", age_band="24")
AT = 1_753_185_600_000


def matched():  # type: ignore[no-untyped-def]
    return record_interest(
        create_conversation_state(),
        candidate=CANDIDATE,
        starter_tag="hiking",
        reciprocal_like=True,
        at_ms=AT,
    )


def test_unilateral_interest_is_pending_and_match_requires_reciprocity() -> None:
    pending = record_interest(
        create_conversation_state(),
        candidate=CANDIDATE,
        starter_tag="hiking",
        reciprocal_like=False,
        at_ms=AT,
    )
    assert pending.outcome["kind"] == "interest_pending"
    assert pending.outcome["matched"] is False
    assert not pending.state.matches

    created = matched()
    match = created.state.matches[str(created.outcome["match_id"])]
    assert match.status is MatchStatus.ACTIVE
    assert match.starter_tag == "hiking"
    assert match.messages == ()
    assert match.message_limit == INITIAL_MESSAGE_LIMIT


def test_pass_and_pending_interest_can_be_undone_but_match_cannot() -> None:
    passed = record_pass(create_conversation_state(), candidate_id="p2", at_ms=AT)
    undone = undo_last_decision(passed.state)
    assert undone.outcome["restored_candidate_id"] == "p2"
    assert undone.state.decisions == ()

    pending = record_interest(
        create_conversation_state(),
        candidate=CANDIDATE,
        starter_tag="live_music",
        reciprocal_like=False,
        at_ms=AT,
    )
    assert undo_last_decision(pending.state).outcome["kind"] == "decision_undone"
    no_undo = undo_last_decision(matched().state)
    assert no_undo.outcome["kind"] == "match_requires_unmatch"


def test_interest_does_not_require_shared_ground_and_respects_availability() -> None:
    created = record_interest(
        create_conversation_state(),
        candidate=CANDIDATE,
        reciprocal_like=True,
        at_ms=AT,
    )
    assert created.state.matches[str(created.outcome["match_id"])].starter_tag is None
    first = record_pass(create_conversation_state(), candidate_id="p1", at_ms=AT)
    with pytest.raises(DomainError, match="candidate_already_decided"):
        record_interest(first.state, candidate=CANDIDATE, at_ms=AT)


def test_first_message_does_not_require_shared_ground() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    sent = send_message(
        created.state,
        match_id=match_id,
        text="What trail do you like?",
        at_ms=AT,
    )
    assert sent.value.shared_ground_tag is None
    second = send_message(
        sent.state,
        match_id=match_id,
        text="Another message",
        at_ms=AT + 1,
    )
    assert second.value.shared_ground_tag is None


def test_message_validation_and_synthetic_reply() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    with pytest.raises(DomainError, match="message_required"):
        send_message(created.state, match_id=match_id, text=" ", at_ms=AT)
    sent = send_message(
        created.state,
        match_id=match_id,
        text="x" * 500,
        at_ms=AT,
    )
    with pytest.raises(DomainError, match="message_too_long"):
        send_message(created.state, match_id=match_id, text="x" * 501, at_ms=AT)
    replied = receive_synthetic_reply(
        sent.state,
        match_id=match_id,
        text="I like the river loop.",
        at_ms=AT + 1,
    )
    assert replied.value.sender == "candidate"
    assert len(replied.state.matches[match_id].messages) == 2


def test_twenty_message_limit_allows_one_extension() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    state = created.state
    for index in range(INITIAL_MESSAGE_LIMIT):
        state = send_message(
            state,
            match_id=match_id,
            text=f"message {index}",
            at_ms=AT + index,
        ).state

    with pytest.raises(DomainError, match="message_limit_reached"):
        send_message(
            state,
            match_id=match_id,
            text="one too many",
            at_ms=AT + 30,
        )

    extended = extend_conversation(state, match_id=match_id)
    assert extended.state.matches[match_id].message_limit == 40
    assert extended.state.matches[match_id].extension_used is True
    with pytest.raises(DomainError, match="message_extension_already_used"):
        extend_conversation(extended.state, match_id=match_id)


def test_extension_is_not_available_early() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    with pytest.raises(DomainError, match="message_extension_not_available"):
        extend_conversation(created.state, match_id=match_id)


def test_unmatch_retains_transcript_while_block_purges_and_suppresses() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    sent = send_message(created.state, match_id=match_id, text="Opening", at_ms=AT)
    ended = unmatch_conversation(sent.state, match_id=match_id, at_ms=AT + 1)
    assert ended.state.matches[match_id].status is MatchStatus.UNMATCHED
    assert len(ended.state.matches[match_id].messages) == 1
    with pytest.raises(DomainError, match="match_not_active"):
        send_message(ended.state, match_id=match_id, text="Still there?", at_ms=AT + 2)

    blocked = block_conversation(sent.state, match_id=match_id, at_ms=AT + 1)
    match = blocked.state.matches[match_id]
    assert match.status is MatchStatus.BLOCKED
    assert match.content_purged
    assert match.messages == ()
    assert match.starter_tag is None
    assert "p1" in get_suppressed_candidate_ids(blocked.state)


def test_starter_suggestions_are_optional_and_person_specific() -> None:
    created = matched()
    match = created.state.matches[str(created.outcome["match_id"])]
    suggestions = build_starter_suggestions(match)
    assert len(suggestions) == 3
    assert all("Alex" in suggestion for suggestion in suggestions)


def test_meetup_suggestions_are_grounded_public_and_location_free() -> None:
    created = matched()
    match = created.state.matches[str(created.outcome["match_id"])]
    suggestions = build_meetup_suggestions(match)
    assert [suggestion.id for suggestion in suggestions] == [
        "coffee_public",
        "museum_daytime",
        "public_activity",
    ]
    assert all("public" in suggestion.prompt for suggestion in suggestions)
    assert all("no location has been shared" in suggestion.prompt for suggestion in suggestions)


def test_meetup_proposal_is_available_immediately_after_match() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    proposed = send_meetup_proposal(
        created.state,
        match_id=match_id,
        suggestion_id="coffee_public",
        at_ms=AT + 1,
    )
    assert proposed.value.sender == "local"
    assert proposed.value.body.startswith("Would you like to meet for coffee")
    assert proposed.state.matches[match_id].messages[-1] == proposed.value


def test_unknown_meetup_suggestion_is_rejected() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    with pytest.raises(DomainError, match="unknown_meetup_suggestion"):
        send_meetup_proposal(
            created.state,
            match_id=match_id,
            suggestion_id="private_address",
            at_ms=AT + 2,
        )
