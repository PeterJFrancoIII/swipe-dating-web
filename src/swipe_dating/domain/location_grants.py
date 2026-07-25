"""Metadata-only, match-scoped location grant decisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.models import is_safe_integer


class LocationMode(StrEnum):
    NONE = "none"
    APPROXIMATE_MATCH_AREA = "approximate_match_area"
    MEETING_PIN = "meeting_pin"
    LIVE_15_MINUTES = "live_15_minutes"
    LIVE_1_HOUR = "live_1_hour"
    LIVE_4_HOURS = "live_4_hours"


MAX_DURATION_MS: Final = {
    LocationMode.APPROXIMATE_MATCH_AREA: 24 * 60 * 60 * 1_000,
    LocationMode.MEETING_PIN: 24 * 60 * 60 * 1_000,
    LocationMode.LIVE_15_MINUTES: 15 * 60 * 1_000,
    LocationMode.LIVE_1_HOUR: 60 * 60 * 1_000,
    LocationMode.LIVE_4_HOURS: 4 * 60 * 60 * 1_000,
}

PRECISE_MODES: Final = frozenset(
    {
        LocationMode.MEETING_PIN,
        LocationMode.LIVE_15_MINUTES,
        LocationMode.LIVE_1_HOUR,
        LocationMode.LIVE_4_HOURS,
    }
)


@dataclass(frozen=True, slots=True)
class LocationGrant:
    share_id: str
    sender_profile_id: str
    recipient_profile_id: str
    mode: LocationMode
    issued_at_ms: int
    expires_at_ms: int
    sequence: int
    precise_confirmation: bool
    revoked_at_ms: int | None = None


def issue_location_grant(
    *,
    share_id: str,
    sender_profile_id: str,
    recipient_profile_id: str,
    mode: LocationMode | str,
    issued_at_ms: int,
    sequence: int,
    precise_confirmation: bool = False,
) -> LocationGrant:
    if not share_id or not sender_profile_id or not recipient_profile_id:
        raise DomainError("location_identifiers_required")
    if sender_profile_id == recipient_profile_id:
        raise DomainError("cannot_share_location_to_self")
    try:
        selected_mode = LocationMode(mode)
    except ValueError as error:
        raise DomainError("unsupported_location_mode") from error
    if selected_mode not in MAX_DURATION_MS:
        raise DomainError("unsupported_location_mode")
    if selected_mode in PRECISE_MODES and not precise_confirmation:
        raise DomainError("precise_confirmation_required")
    if not is_safe_integer(issued_at_ms) or not is_safe_integer(sequence) or sequence < 0:
        raise DomainError("invalid_location_issue")
    return LocationGrant(
        share_id=share_id,
        sender_profile_id=sender_profile_id,
        recipient_profile_id=recipient_profile_id,
        mode=selected_mode,
        issued_at_ms=issued_at_ms,
        expires_at_ms=issued_at_ms + MAX_DURATION_MS[selected_mode],
        sequence=sequence,
        precise_confirmation=precise_confirmation,
    )


def location_grant_is_active(grant: LocationGrant, now_ms: int) -> bool:
    return grant.revoked_at_ms is None and grant.issued_at_ms <= now_ms < grant.expires_at_ms


def revoke_location_grant(grant: LocationGrant, revoked_at_ms: int) -> LocationGrant:
    if not is_safe_integer(revoked_at_ms) or revoked_at_ms < grant.issued_at_ms:
        raise DomainError("invalid_revocation_time")
    return replace(grant, sequence=grant.sequence + 1, revoked_at_ms=revoked_at_ms)
