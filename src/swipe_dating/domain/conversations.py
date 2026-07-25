"""Session-only reciprocal match and conversation state machine."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.models import (
    TransitionResult,
    ValueResult,
    frozen_mapping,
    frozen_outcome,
    iso_from_ms,
)


class MatchStatus(StrEnum):
    ACTIVE = "active"
    UNMATCHED = "unmatched"
    BLOCKED = "blocked"


class DecisionKind(StrEnum):
    PASS = "pass"
    INTEREST = "interest"


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    id: str
    display_name: str = "Synthetic profile"
    age_band: str = "adult"


@dataclass(frozen=True, slots=True)
class Decision:
    id: str
    candidate_id: str
    kind: DecisionKind
    starter_tag: str | None
    creates_match: bool
    at: str


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    sender: str
    body: str
    shared_ground_tag: str | None
    sent_at: str


@dataclass(frozen=True, slots=True)
class MeetupSuggestion:
    id: str
    title: str
    prompt: str


@dataclass(frozen=True, slots=True)
class ConversationMatch:
    id: str
    candidate: CandidateSnapshot
    status: MatchStatus
    starter_tag: str | None
    opened_at: str
    ended_at: str | None = None
    content_purged: bool = False
    messages: tuple[Message, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationState:
    decisions: tuple[Decision, ...]
    matches: Mapping[str, ConversationMatch]
    blocked_candidate_ids: tuple[str, ...]
    next_event_sequence: int = 1
    next_message_sequence: int = 1
    last_restored_candidate_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decisions", tuple(self.decisions))
        object.__setattr__(self, "matches", frozen_mapping(self.matches))
        object.__setattr__(self, "blocked_candidate_ids", tuple(self.blocked_candidate_ids))


def create_conversation_state() -> ConversationState:
    return ConversationState((), {}, ())


def record_pass(
    state: ConversationState,
    *,
    candidate_id: str,
    at_ms: int | float | None = None,
) -> TransitionResult[ConversationState]:
    _assert_candidate_available(state, candidate_id)
    decision = Decision(
        id=f"decision-{state.next_event_sequence}",
        candidate_id=candidate_id,
        kind=DecisionKind.PASS,
        starter_tag=None,
        creates_match=False,
        at=_to_iso(at_ms),
    )
    next_state = replace(
        state,
        decisions=(*state.decisions, decision),
        next_event_sequence=state.next_event_sequence + 1,
        last_restored_candidate_id=None,
    )
    return TransitionResult(next_state, frozen_outcome(kind="passed", candidate_id=candidate_id))


def record_interest(
    state: ConversationState,
    *,
    candidate: CandidateSnapshot | object,
    starter_tag: str | None = None,
    reciprocal_like: bool = False,
    at_ms: int | float | None = None,
) -> TransitionResult[ConversationState]:
    snapshot = _sanitize_candidate_snapshot(candidate)
    _assert_candidate_available(state, snapshot.id)
    normalized_starter = _normalize_tag(starter_tag) or None
    at = _to_iso(at_ms)
    decision = Decision(
        id=f"decision-{state.next_event_sequence}",
        candidate_id=snapshot.id,
        kind=DecisionKind.INTEREST,
        starter_tag=normalized_starter,
        creates_match=bool(reciprocal_like),
        at=at,
    )
    decisions = (*state.decisions, decision)
    if not reciprocal_like:
        next_state = replace(
            state,
            decisions=decisions,
            next_event_sequence=state.next_event_sequence + 1,
            last_restored_candidate_id=None,
        )
        return TransitionResult(
            next_state,
            frozen_outcome(kind="interest_pending", candidate_id=snapshot.id, matched=False),
        )

    match_id = f"match:{snapshot.id}"
    match = ConversationMatch(
        id=match_id,
        candidate=snapshot,
        status=MatchStatus.ACTIVE,
        starter_tag=normalized_starter,
        opened_at=at,
    )
    next_state = replace(
        state,
        decisions=decisions,
        matches={**state.matches, match_id: match},
        next_event_sequence=state.next_event_sequence + 1,
        last_restored_candidate_id=None,
    )
    return TransitionResult(
        next_state,
        frozen_outcome(
            kind="match_created",
            candidate_id=snapshot.id,
            match_id=match_id,
            matched=True,
        ),
    )


def undo_last_decision(state: ConversationState) -> TransitionResult[ConversationState]:
    if not state.decisions:
        return TransitionResult(
            state,
            frozen_outcome(kind="nothing_to_undo", restored_candidate_id=None),
        )
    decision = state.decisions[-1]
    if decision.creates_match:
        return TransitionResult(
            state,
            frozen_outcome(
                kind="match_requires_unmatch",
                restored_candidate_id=None,
                match_id=f"match:{decision.candidate_id}",
            ),
        )
    next_state = replace(
        state,
        decisions=state.decisions[:-1],
        last_restored_candidate_id=decision.candidate_id,
    )
    return TransitionResult(
        next_state,
        frozen_outcome(kind="decision_undone", restored_candidate_id=decision.candidate_id),
    )


def send_message(
    state: ConversationState,
    *,
    match_id: str,
    text: str,
    shared_ground_tag: str | None = None,
    at_ms: int | float | None = None,
) -> ValueResult[ConversationState, Message]:
    match = _require_active_match(state, match_id)
    body = _normalize_message(text)
    _ = shared_ground_tag  # Call-site compatibility only; openers are not required.
    message = Message(
        id=f"message-{state.next_message_sequence}",
        sender="local",
        body=body,
        shared_ground_tag=None,
        sent_at=_to_iso(at_ms),
    )
    next_match = replace(match, messages=(*match.messages, message))
    next_state = _replace_match(
        state,
        match_id,
        next_match,
        next_message_sequence=state.next_message_sequence + 1,
    )
    return ValueResult(next_state, message)


def receive_synthetic_reply(
    state: ConversationState,
    *,
    match_id: str,
    text: str,
    at_ms: int | float | None = None,
) -> ValueResult[ConversationState, Message]:
    match = _require_active_match(state, match_id)
    message = Message(
        id=f"message-{state.next_message_sequence}",
        sender="candidate",
        body=_normalize_message(text),
        shared_ground_tag=None,
        sent_at=_to_iso(at_ms),
    )
    next_match = replace(match, messages=(*match.messages, message))
    next_state = _replace_match(
        state,
        match_id,
        next_match,
        next_message_sequence=state.next_message_sequence + 1,
    )
    return ValueResult(next_state, message)


def unmatch_conversation(
    state: ConversationState,
    *,
    match_id: str,
    at_ms: int | float | None = None,
) -> TransitionResult[ConversationState]:
    match = _require_match(state, match_id)
    if match.status is not MatchStatus.ACTIVE:
        return TransitionResult(state, frozen_outcome(kind="already_ended", match_id=match_id))
    next_state = _replace_match(
        state,
        match_id,
        replace(match, status=MatchStatus.UNMATCHED, ended_at=_to_iso(at_ms)),
    )
    return TransitionResult(
        next_state,
        frozen_outcome(kind="unmatched", match_id=match_id, candidate_id=match.candidate.id),
    )


def block_conversation(
    state: ConversationState,
    *,
    match_id: str,
    at_ms: int | float | None = None,
) -> TransitionResult[ConversationState]:
    match = _require_match(state, match_id)
    blocked = _unique((*state.blocked_candidate_ids, match.candidate.id))
    next_match = replace(
        match,
        status=MatchStatus.BLOCKED,
        starter_tag=None,
        ended_at=_to_iso(at_ms),
        content_purged=True,
        messages=(),
    )
    next_state = _replace_match(replace(state, blocked_candidate_ids=blocked), match_id, next_match)
    return TransitionResult(
        next_state,
        frozen_outcome(kind="blocked", match_id=match_id, candidate_id=match.candidate.id),
    )


def build_starter_suggestions(match: ConversationMatch) -> tuple[str, ...]:
    # Forced openers are out of product scope; keep a small optional catalog for tests.
    name = match.candidate.display_name or "them"
    return (
        f"Hi {name} — what's something you're looking forward to this week?",
        f"Hi {name} — want to compare favorite public hangouts?",
        f"Hi {name} — open to planning a low-pressure meetup?",
    )


def build_meetup_suggestions(match: ConversationMatch) -> tuple[MeetupSuggestion, ...]:
    if match.status is not MatchStatus.ACTIVE:
        raise DomainError("match_not_active")
    safety = "This is only a proposal; no location has been shared."
    return (
        MeetupSuggestion(
            "coffee_public",
            "Coffee in a public place",
            f"Would you like to meet for coffee in a public place? {safety}",
        ),
        MeetupSuggestion(
            "museum_daytime",
            "Daytime public museum visit",
            f"Would you like to visit a public museum during daytime hours? {safety}",
        ),
        MeetupSuggestion(
            "public_activity",
            "Low-pressure public activity",
            "Would you like to choose a low-pressure activity in a well-populated public "
            f"place? {safety}",
        ),
    )


def send_meetup_proposal(
    state: ConversationState,
    *,
    match_id: str,
    suggestion_id: str,
    at_ms: int | float | None = None,
) -> ValueResult[ConversationState, Message]:
    match = _require_active_match(state, match_id)
    senders = {message.sender for message in match.messages}
    if not {"local", "candidate"}.issubset(senders):
        raise DomainError("meetup_requires_two_way_conversation")
    suggestions = {suggestion.id: suggestion for suggestion in build_meetup_suggestions(match)}
    try:
        suggestion = suggestions[suggestion_id]
    except KeyError as error:
        raise DomainError("unknown_meetup_suggestion") from error
    return send_message(state, match_id=match_id, text=suggestion.prompt, at_ms=at_ms)


def list_matches(state: ConversationState) -> tuple[ConversationMatch, ...]:
    return tuple(sorted(state.matches.values(), key=lambda match: match.opened_at, reverse=True))


def get_suppressed_candidate_ids(state: ConversationState) -> tuple[str, ...]:
    return _unique(
        (
            *state.blocked_candidate_ids,
            *(decision.candidate_id for decision in state.decisions),
            *(match.candidate.id for match in state.matches.values()),
        )
    )


def is_candidate_blocked(state: ConversationState, candidate_id: str) -> bool:
    return candidate_id in state.blocked_candidate_ids


def _assert_candidate_available(state: ConversationState, candidate_id: str) -> None:
    if not candidate_id or not isinstance(candidate_id, str):
        raise DomainError("candidate_id_required")
    if is_candidate_blocked(state, candidate_id):
        raise DomainError("candidate_blocked")
    if candidate_id in get_suppressed_candidate_ids(state):
        raise DomainError("candidate_already_decided")


def _require_match(state: ConversationState, match_id: str) -> ConversationMatch:
    try:
        return state.matches[match_id]
    except KeyError as error:
        raise DomainError("match_not_found") from error


def _require_active_match(state: ConversationState, match_id: str) -> ConversationMatch:
    match = _require_match(state, match_id)
    if match.status is not MatchStatus.ACTIVE:
        raise DomainError("match_not_active")
    return match


def _replace_match(
    state: ConversationState,
    match_id: str,
    match: ConversationMatch,
    *,
    next_message_sequence: int | None = None,
) -> ConversationState:
    return replace(
        state,
        matches={**state.matches, match_id: match},
        next_message_sequence=(
            state.next_message_sequence if next_message_sequence is None else next_message_sequence
        ),
    )


def _sanitize_candidate_snapshot(candidate: CandidateSnapshot | object) -> CandidateSnapshot:
    source_id: object
    display_name: object
    age_band: object
    if isinstance(candidate, CandidateSnapshot):
        source_id = candidate.id
        display_name = candidate.display_name
        age_band = candidate.age_band
    elif isinstance(candidate, Mapping):
        source_id = candidate.get("id")
        display_name = candidate.get(
            "displayName", candidate.get("display_name", "Synthetic profile")
        )
        age_band = candidate.get("ageBand", candidate.get("age_band", "adult"))
    else:
        source_id = getattr(candidate, "id", None)
        display_name = getattr(candidate, "display_name", "Synthetic profile")
        age_band = getattr(candidate, "age_band", "adult")
    candidate_id = str(source_id or "").strip()
    if not candidate_id:
        raise DomainError("candidate_id_required")
    return CandidateSnapshot(
        candidate_id,
        str(display_name or "Synthetic profile").strip()[:64],
        str(age_band or "adult").strip()[:32],
    )


def _normalize_tag(value: str | None) -> str:
    return value.strip()[:80] if isinstance(value, str) else ""


def _normalize_message(value: str) -> str:
    body = value.strip() if isinstance(value, str) else ""
    if not body:
        raise DomainError("message_required")
    if len(body) > 500:
        raise DomainError("message_too_long")
    return body


def _to_iso(at_ms: int | float | None) -> str:
    return iso_from_ms(time.time() * 1_000 if at_ms is None else at_ms)


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
