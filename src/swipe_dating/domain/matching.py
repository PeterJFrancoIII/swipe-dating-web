"""In-memory synthetic rendezvous, reciprocal likes, and blocks."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from swipe_dating.domain.adult import AdultCredential, adult_credential_is_valid
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.models import is_safe_integer


@dataclass(frozen=True, slots=True)
class PresenceLease:
    profile_id: str
    region: str
    issued_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True, slots=True)
class MatchReceipt:
    profile_a: str
    profile_b: str
    matched_at_ms: int


class RendezvousStore:
    """Process-local R&D store. It is not a production match authority."""

    def __init__(self) -> None:
        self._presence: dict[str, PresenceLease] = {}
        self._likes: set[tuple[str, str]] = set()
        self._blocks: set[tuple[str, str]] = set()
        self._lock = RLock()

    def publish_presence(
        self,
        *,
        profile_id: str,
        region: str,
        issued_at_ms: int,
        expires_at_ms: int,
        adult_credential: AdultCredential,
    ) -> PresenceLease:
        if not adult_credential_is_valid(
            adult_credential, subject_id=profile_id, now_ms=issued_at_ms
        ):
            raise DomainError("adult_credential_subject_bound")
        if not isinstance(region, str) or not 1 <= len(region) <= 64 or "," in region:
            raise DomainError("invalid_coarse_region")
        ttl_ms = expires_at_ms - issued_at_ms
        if not is_safe_integer(ttl_ms) or not 1 <= ttl_ms <= 120_000:
            raise DomainError("presence_ttl_out_of_range")
        lease = PresenceLease(profile_id, region, issued_at_ms, expires_at_ms)
        with self._lock:
            self._presence[profile_id] = lease
        return lease

    def withdraw_presence(self, profile_id: str) -> bool:
        with self._lock:
            return self._presence.pop(profile_id, None) is not None

    def discover(
        self,
        *,
        region: str,
        requester_profile_id: str,
        now_ms: int,
        limit: int = 20,
    ) -> tuple[str, ...]:
        with self._lock:
            self._expire(now_ms)
            bounded_limit = max(0, min(20, limit)) if isinstance(limit, int) else 0
            values = sorted(
                lease.profile_id
                for lease in self._presence.values()
                if lease.region == region
                and lease.profile_id != requester_profile_id
                and not self._is_blocked(requester_profile_id, lease.profile_id)
            )
            return tuple(values[:bounded_limit])

    def record_like(
        self,
        *,
        sender_profile_id: str,
        recipient_profile_id: str,
        now_ms: int,
    ) -> MatchReceipt | None:
        if sender_profile_id == recipient_profile_id:
            raise DomainError("cannot_like_self")
        with self._lock:
            if self._is_blocked(sender_profile_id, recipient_profile_id):
                raise DomainError("interaction_blocked")
            self._likes.add((sender_profile_id, recipient_profile_id))
            if (recipient_profile_id, sender_profile_id) not in self._likes:
                return None
            profile_a, profile_b = sorted((sender_profile_id, recipient_profile_id))
            return MatchReceipt(profile_a, profile_b, now_ms)

    def block(self, *, blocker_profile_id: str, blocked_profile_id: str) -> None:
        if blocker_profile_id == blocked_profile_id:
            raise DomainError("cannot_block_self")
        with self._lock:
            self._blocks.add((blocker_profile_id, blocked_profile_id))
            self._likes.discard((blocker_profile_id, blocked_profile_id))
            self._likes.discard((blocked_profile_id, blocker_profile_id))

    def _expire(self, now_ms: int) -> None:
        expired = [
            profile_id
            for profile_id, lease in self._presence.items()
            if lease.expires_at_ms <= now_ms
        ]
        for profile_id in expired:
            del self._presence[profile_id]

    def _is_blocked(self, left: str, right: str) -> bool:
        return (left, right) in self._blocks or (right, left) in self._blocks
