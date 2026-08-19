"""Daily free swipe allotment. Extra swipes stay out of this slice."""

from __future__ import annotations

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.system_config import config_int

DAILY_SWIPE_LIMIT = "daily_swipe_limit"


def charges_daily_swipe(candidate: object) -> bool:
    """Real members consume the 30. Labeled synthetic testing cards do not."""
    return not bool(getattr(candidate, "synthetic", False))


def daily_swipe_limit() -> int:
    return config_int("daily_free_swipes")


def reset_if_new_day(day: str, used: int, today: str) -> tuple[str, int]:
    if day != today:
        return today, 0
    return day, used


def consume_daily_swipe(day: str, used: int, today: str, *, limit: int | None = None) -> tuple[str, int]:
    next_day, next_used = reset_if_new_day(day, used, today)
    cap = daily_swipe_limit() if limit is None else limit
    if next_used >= cap:
        raise DomainError(DAILY_SWIPE_LIMIT)
    return next_day, next_used + 1


def refund_daily_swipe(day: str, used: int, today: str) -> tuple[str, int]:
    next_day, next_used = reset_if_new_day(day, used, today)
    return next_day, max(0, next_used - 1)


def swipes_remaining(day: str, used: int, today: str, *, limit: int | None = None) -> int:
    next_day, next_used = reset_if_new_day(day, used, today)
    cap = daily_swipe_limit() if limit is None else limit
    return max(0, cap - next_used)
