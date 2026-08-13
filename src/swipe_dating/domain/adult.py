"""Exact adult calendar boundary and synthetic credential rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.models import is_safe_integer

_DATE_ONLY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@dataclass(frozen=True, slots=True)
class AdultCredential:
    subject_id: str
    issued_at_ms: int
    expires_at_ms: int
    issuer: str = "staging-mock"
    revoked: bool = False


def parse_date_only(value: str) -> date | None:
    if not isinstance(value, str):
        return None
    match = _DATE_ONLY.fullmatch(value)
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def is_adult_on(birth_date: str, on_date: str) -> bool:
    birth = parse_date_only(birth_date)
    today = parse_date_only(on_date)
    if birth is None or today is None or birth > today:
        return False

    adult_year = birth.year + 18
    try:
        adult_date = birth.replace(year=adult_year)
    except ValueError:
        # February 29 becomes February 28 in a non-leap eighteenth year.
        adult_date = date(adult_year, 2, 28)
    return today >= adult_date


def completed_age_years(birth_date: str, on_date: str) -> int | None:
    birth = parse_date_only(birth_date)
    today = parse_date_only(on_date)
    if birth is None or today is None or birth > today:
        return None
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def create_adult_credential(
    *,
    subject_id: str,
    issued_at_ms: int,
    expires_at_ms: int,
    issuer: str = "staging-mock",
    revoked: bool = False,
) -> AdultCredential:
    if not subject_id:
        raise DomainError("credential_subject_required")
    if not is_safe_integer(issued_at_ms) or not is_safe_integer(expires_at_ms):
        raise DomainError("credential_timestamp_invalid")
    if expires_at_ms <= issued_at_ms:
        raise DomainError("credential_timestamp_order")
    return AdultCredential(
        subject_id=subject_id,
        issued_at_ms=issued_at_ms,
        expires_at_ms=expires_at_ms,
        issuer=issuer,
        revoked=revoked,
    )


def adult_credential_is_valid(
    credential: AdultCredential | None,
    *,
    subject_id: str,
    now_ms: int,
) -> bool:
    return bool(
        credential is not None
        and credential.subject_id == subject_id
        and credential.revoked is False
        and credential.issued_at_ms <= now_ms < credential.expires_at_ms
    )
