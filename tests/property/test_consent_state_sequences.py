from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from swipe_dating.domain.conversations import (
    CandidateSnapshot,
    ConversationState,
    MatchStatus,
    block_conversation,
    create_conversation_state,
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

CONVERSATION_ACTIONS = (
    "pass",
    "pending_interest",
    "reciprocal_interest",
    "undo",
    "local_message",
    "candidate_reply",
    "meetup",
    "unmatch",
    "block",
)


@settings(max_examples=100, deadline=None)
@given(st.lists(st.sampled_from(CONVERSATION_ACTIONS), min_size=1, max_size=40))
def test_conversation_state_machine_preserves_consent_invariants(
    actions: list[str],
) -> None:
    state = create_conversation_state()
    next_candidate = 1

    for step, action in enumerate(actions, start=1):
        matches = tuple(state.matches.values())
        active_matches = tuple(match for match in matches if match.status is MatchStatus.ACTIVE)

        if action == "pass":
            candidate_id = f"candidate-{next_candidate}"
            next_candidate += 1
            state = record_pass(state, candidate_id=candidate_id, at_ms=step).state
        elif action in {"pending_interest", "reciprocal_interest"}:
            candidate_id = f"candidate-{next_candidate}"
            next_candidate += 1
            state = record_interest(
                state,
                candidate=CandidateSnapshot(candidate_id),
                reciprocal_like=action == "reciprocal_interest",
                at_ms=step,
            ).state
        elif action == "undo":
            state = undo_last_decision(state).state
        elif action == "local_message" and active_matches:
            match = active_matches[-1]
            if len(match.messages) < match.message_limit:
                state = send_message(
                    state,
                    match_id=match.id,
                    text=f"Local message {step}",
                    at_ms=step,
                ).state
        elif action == "candidate_reply" and active_matches:
            match = active_matches[-1]
            if len(match.messages) < match.message_limit:
                state = receive_synthetic_reply(
                    state,
                    match_id=match.id,
                    text=f"Candidate reply {step}",
                    at_ms=step,
                ).state
        elif action == "meetup" and active_matches:
            match = active_matches[-1]
            if len(match.messages) < match.message_limit:
                state = send_meetup_proposal(
                    state,
                    match_id=match.id,
                    suggestion_id="coffee_public",
                    at_ms=step,
                ).state
        elif action == "unmatch" and matches:
            state = unmatch_conversation(state, match_id=matches[-1].id, at_ms=step).state
        elif action == "block" and matches:
            state = block_conversation(state, match_id=matches[-1].id, at_ms=step).state

        _assert_conversation_invariants(state)
        assert state.next_event_sequence == next_candidate


def _assert_conversation_invariants(state: ConversationState) -> None:
    decisions = state.decisions
    matches = tuple(state.matches.values())
    decision_ids = tuple(decision.id for decision in decisions)
    assert len(decision_ids) == len(set(decision_ids))

    match_creating_candidates = {
        decision.candidate_id for decision in decisions if decision.creates_match
    }
    suppressed = set(get_suppressed_candidate_ids(state))
    visible_message_ids: list[str] = []

    for decision in decisions:
        assert decision.candidate_id in suppressed
    for match in matches:
        assert match.candidate.id in match_creating_candidates
        assert match.candidate.id in suppressed
        assert len(match.messages) <= match.message_limit
        local_messages = tuple(message for message in match.messages if message.sender == "local")
        assert all(message.shared_ground_tag is None for message in local_messages)
        visible_message_ids.extend(message.id for message in match.messages)

        if match.status is MatchStatus.BLOCKED:
            assert match.content_purged is True
            assert match.messages == ()
            assert match.starter_tag is None
            assert match.candidate.id in state.blocked_candidate_ids
        elif match.status is not MatchStatus.ACTIVE:
            with pytest.raises(DomainError, match="match_not_active"):
                send_message(state, match_id=match.id, text="No", at_ms=0)

    assert len(visible_message_ids) == len(set(visible_message_ids))
    for message_id in visible_message_ids:
        sequence = int(message_id.removeprefix("message-"))
        assert 1 <= sequence < state.next_message_sequence
    assert set(state.blocked_candidate_ids).issubset(suppressed)
