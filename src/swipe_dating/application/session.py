"""Laptop-session coordinator that preserves the R&D persistence boundary."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import replace

from swipe_dating.adapters.storage import LocalStateRepository
from swipe_dating.domain.adult import is_adult_on, parse_date_only
from swipe_dating.domain.bot_moderation import (
    CommunityMember,
    ModerationCase,
    ModerationState,
    ReportReason,
    VoteChoice,
    adjudicate_bot_case,
    appeal_bot_case,
    cast_bot_vote,
    contained_profile_ids,
    create_moderation_state,
    eligible_reviewer_ids,
    file_bot_report,
    get_moderation_case,
)
from swipe_dating.domain.conversations import (
    ConversationMatch,
    ConversationState,
    Message,
    block_conversation,
    build_meetup_suggestions,
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
from swipe_dating.domain.discovery import (
    DEFAULT_RANKING_WEIGHTS,
    DiscoveryProfile,
    RankedCandidate,
    rank_discovery_candidates,
)
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.local_state import LocalCosmetics, LocalProfile, LocalState, LocalUi
from swipe_dating.domain.profile_readiness import ProfileReadiness, assess_profile_readiness
from swipe_dating.domain.proximity import (
    ProximityDecision,
    ProximityDisclosure,
    decide_proximity_event,
)
from swipe_dating.domain.risk import assess_risk
from swipe_dating.fixtures import (
    LOCAL_VIEWER,
    SKIN_ITEMS,
    SYNTHETIC_BOT_SIGNALS,
    SYNTHETIC_BOT_TRUTH,
    SYNTHETIC_COMMUNITY_MEMBERS,
    SYNTHETIC_PROFILES,
)

APP_TABS = ("Swipe", "Matches")


class ResearchSession:
    """Orchestrate one synthetic session; persist only approved presentation fields."""

    def __init__(
        self,
        *,
        repository: LocalStateRepository,
        clock: Callable[[], int] | None = None,
        today: str = "2026-07-22",
        profiles: tuple[DiscoveryProfile, ...] = SYNTHETIC_PROFILES,
    ) -> None:
        self.repository = repository
        self.clock = clock if clock is not None else lambda: int(time.time() * 1_000)
        self.today = today
        loaded = repository.load()
        self.local_state = loaded.state
        self.storage_recovered = loaded.recovered
        self.storage_reason = loaded.reason
        self.saved_at = loaded.saved_at
        self.active_tab = self.local_state.ui.last_tab

        self.adult_accepted = False
        self.birth_date = ""
        self.get_fkd_enabled = False
        self.proximity_disclosure = ProximityDisclosure.PROMPT_BEFORE_SHARING
        self.location_choice = "none"

        self.immediate_intent = LOCAL_VIEWER.immediate_intent
        self.relational_openness = LOCAL_VIEWER.relational_openness
        self.required_boundaries = set(LOCAL_VIEWER.required_boundaries)

        self.selected_intents: set[str] = {"dating"}
        self.selected_genders: set[str] = set()
        self.questionnaire_answers: dict[str, str] = {}

        self.conversations: ConversationState = create_conversation_state()
        self.moderation_state: ModerationState = create_moderation_state(
            SYNTHETIC_COMMUNITY_MEMBERS
        )
        self._profiles = tuple(profiles)
        self._profiles_by_id = {profile.id: profile for profile in self._profiles}

    def accept_adult_gate(self, birth_date: str) -> None:
        normalized = birth_date.strip()
        if parse_date_only(normalized) is None:
            raise DomainError("birth_date_invalid")
        if not is_adult_on(normalized, self.today):
            raise DomainError("adult_only")
        self.birth_date = normalized
        self.adult_accepted = True

    def viewer(self) -> DiscoveryProfile:
        boundaries = tuple(
            boundary for boundary in LOCAL_VIEWER.boundaries if boundary in self.required_boundaries
        )
        extras = tuple(sorted(self.required_boundaries.difference(LOCAL_VIEWER.boundaries)))
        selected_boundaries = (*boundaries, *extras)
        return replace(
            LOCAL_VIEWER,
            immediate_intent=self.immediate_intent,
            relational_openness=self.relational_openness,
            boundaries=selected_boundaries,
            required_boundaries=selected_boundaries,
        )

    def discovery_queue(self) -> tuple[RankedCandidate, ...]:
        suppressed = {
            *get_suppressed_candidate_ids(self.conversations),
            *contained_profile_ids(self.moderation_state),
        }
        return tuple(
            entry
            for entry in rank_discovery_candidates(
                self.viewer(), self._profiles, DEFAULT_RANKING_WEIGHTS
            )
            if entry.candidate.id not in suppressed
        )

    def current_candidate(self) -> RankedCandidate | None:
        queue = self.discovery_queue()
        return queue[0] if queue else None

    def candidate_profile(self, candidate_id: str) -> DiscoveryProfile:
        return self._candidate(candidate_id)

    def active_matches(self) -> tuple[ConversationMatch, ...]:
        return tuple(
            match
            for match in self.conversations.matches.values()
            if match.status.value == "active"
        )

    def match(self, match_id: str) -> ConversationMatch:
        try:
            return self.conversations.matches[match_id]
        except KeyError as error:
            raise DomainError("match_not_found") from error

    def meetup_suggestions(self, match_id: str) -> tuple[object, ...]:
        return build_meetup_suggestions(self.match(match_id))

    def pass_candidate(self, candidate_id: str) -> Mapping[str, object]:
        self._require_adult()
        self._require_candidate_not_contained(candidate_id)
        result = record_pass(self.conversations, candidate_id=candidate_id, at_ms=self.clock())
        self.conversations = result.state
        return result.outcome

    def express_interest(self, candidate_id: str) -> Mapping[str, object]:
        self._require_adult()
        self._require_candidate_not_contained(candidate_id)
        candidate = self._candidate(candidate_id)
        result = record_interest(
            self.conversations,
            candidate=candidate,
            reciprocal_like=candidate.synthetic_reciprocal_like,
            at_ms=self.clock(),
        )
        self.conversations = result.state
        if result.outcome.get("matched") is True:
            self.active_tab = "Matches"
        return result.outcome

    def report_suspected_bot(
        self,
        candidate_id: str,
        reason: ReportReason,
        evidence_note: str = "",
    ) -> ModerationCase:
        self._require_adult()
        self._candidate(candidate_id)
        signals = SYNTHETIC_BOT_SIGNALS.get(
            candidate_id,
            {
                "adultCredentialValid": False,
                "attestation": "missing",
            },
        )
        result = file_bot_report(
            self.moderation_state,
            reporter_id=LOCAL_VIEWER.id,
            subject_profile_id=candidate_id,
            reason=reason,
            risk_assessment=assess_risk(signals),
            at_ms=self.clock(),
            evidence_note=evidence_note,
        )
        self.moderation_state = result.state
        return result.value

    def vote_on_bot_case(
        self,
        case_id: str,
        reviewer_id: str,
        choice: VoteChoice,
    ) -> ModerationCase:
        self._require_adult()
        result = cast_bot_vote(
            self.moderation_state,
            case_id=case_id,
            reviewer_id=reviewer_id,
            choice=choice,
            at_ms=self.clock(),
        )
        self.moderation_state = result.state
        return result.value

    def appeal_bot_containment(self, case_id: str) -> ModerationCase:
        self._require_adult()
        case = get_moderation_case(self.moderation_state, case_id)
        result = appeal_bot_case(
            self.moderation_state,
            case_id=case_id,
            subject_profile_id=case.report.subject_profile_id,
        )
        self.moderation_state = result.state
        return result.value

    def run_synthetic_adjudication(self, case_id: str) -> ModerationCase:
        self._require_adult()
        case = get_moderation_case(self.moderation_state, case_id)
        try:
            confirmed_bot = SYNTHETIC_BOT_TRUTH[case.report.subject_profile_id]
        except KeyError as error:
            raise DomainError("synthetic_truth_missing") from error
        result = adjudicate_bot_case(
            self.moderation_state,
            case_id=case_id,
            confirmed_bot=confirmed_bot,
        )
        self.moderation_state = result.state
        return result.value

    def moderation_cases(self) -> tuple[ModerationCase, ...]:
        return tuple(self.moderation_state.cases.values())

    def eligible_reviewers(self, case_id: str) -> tuple[CommunityMember, ...]:
        return tuple(
            self.moderation_state.members[reviewer_id]
            for reviewer_id in eligible_reviewer_ids(self.moderation_state, case_id)
        )

    def undo_last_decision(self) -> Mapping[str, object]:
        result = undo_last_decision(self.conversations)
        self.conversations = result.state
        if result.outcome.get("restored_candidate_id"):
            self.active_tab = "Swipe"
        return result.outcome

    def send_message(
        self, match_id: str, text: str, shared_ground_tag: str | None = None
    ) -> Message:
        self._require_adult()
        result = send_message(
            self.conversations,
            match_id=match_id,
            text=text,
            shared_ground_tag=shared_ground_tag,
            at_ms=self.clock(),
        )
        self.conversations = result.state
        return result.value

    def receive_synthetic_reply(self, match_id: str, text: str) -> Message:
        self._require_adult()
        result = receive_synthetic_reply(
            self.conversations, match_id=match_id, text=text, at_ms=self.clock()
        )
        self.conversations = result.state
        return result.value

    def propose_meetup(self, match_id: str, suggestion_id: str) -> Message:
        self._require_adult()
        result = send_meetup_proposal(
            self.conversations,
            match_id=match_id,
            suggestion_id=suggestion_id,
            at_ms=self.clock(),
        )
        self.conversations = result.state
        return result.value

    def unmatch(self, match_id: str) -> Mapping[str, object]:
        conversation = unmatch_conversation(
            self.conversations, match_id=match_id, at_ms=self.clock()
        )
        self.conversations = conversation.state
        return conversation.outcome

    def block(self, match_id: str) -> Mapping[str, object]:
        conversation = block_conversation(self.conversations, match_id=match_id, at_ms=self.clock())
        self.conversations = conversation.state
        return conversation.outcome

    def update_profile(
        self,
        *,
        display_name: str,
        about: str,
        pronouns: str,
    ) -> LocalState:
        self.local_state = replace(
            self.local_state,
            profile=LocalProfile(display_name, about, pronouns),
        )
        return self._persist()

    def update_preferences(
        self,
        *,
        immediate_intent: str,
        relational_openness: str,
        required_boundaries: tuple[str, ...],
    ) -> None:
        if immediate_intent:
            self.immediate_intent = immediate_intent
        if relational_openness:
            self.relational_openness = relational_openness
        self.required_boundaries = set(required_boundaries)

    def profile_readiness(self) -> ProfileReadiness:
        profile = self.local_state.profile
        return assess_profile_readiness(profile.display_name, profile.about)

    def set_haptics(self, enabled: bool) -> LocalState:
        self.local_state = replace(
            self.local_state,
            ui=replace(self.local_state.ui, haptics_enabled=bool(enabled)),
        )
        return self._persist()

    def select_tab(self, tab: str) -> LocalState:
        if tab not in APP_TABS:
            raise DomainError("unknown_tab")
        self.active_tab = tab
        if tab != "Matches":
            self.local_state = replace(
                self.local_state,
                ui=LocalUi(self.local_state.ui.haptics_enabled, tab),
            )
            return self._persist()
        return self.local_state

    def acquire_or_apply_skin(self, skin_id: str) -> LocalState:
        known = {item[0] for item in SKIN_ITEMS}
        if skin_id not in known:
            raise DomainError("unknown_skin")
        owned = tuple(dict.fromkeys((*self.local_state.cosmetics.owned_skin_ids, skin_id)))
        self.local_state = replace(
            self.local_state,
            cosmetics=LocalCosmetics(owned, skin_id),
        )
        return self._persist()

    def reset_saved_profile(self) -> LocalState:
        self.local_state = self.repository.clear()
        self.active_tab = "Swipe"
        return self.local_state

    def export_saved_profile(self) -> str:
        return self.repository.export_text()

    def simulate_proximity(self) -> ProximityDecision:
        return decide_proximity_event(
            adult_credential_valid=self.adult_accepted,
            disclosure=(
                self.proximity_disclosure if self.get_fkd_enabled else ProximityDisclosure.OFF
            ),
            independently_compatible=True,
        )

    def _persist(self) -> LocalState:
        saved = self.repository.save(self.local_state, now_ms=self.clock())
        self.local_state = saved.state
        self.saved_at = saved.saved_at
        return self.local_state

    def _candidate(self, candidate_id: str) -> DiscoveryProfile:
        try:
            return self._profiles_by_id[candidate_id]
        except KeyError as error:
            raise DomainError("candidate_not_found") from error

    def _require_candidate_not_contained(self, candidate_id: str) -> None:
        if candidate_id in contained_profile_ids(self.moderation_state):
            raise DomainError("candidate_temporarily_contained")

    def _require_adult(self) -> None:
        if not self.adult_accepted:
            raise DomainError("adult_gate_required")
