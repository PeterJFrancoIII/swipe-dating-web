"""Small immutable primitives shared by domain modules."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from swipe_dating.domain.errors import DomainError

MAX_SAFE_INTEGER = 9_007_199_254_740_991


@dataclass(frozen=True, slots=True)
class TransitionResult[StateT]:
    state: StateT
    outcome: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ValueResult[StateT, ValueT]:
    state: StateT
    value: ValueT


def frozen_mapping[ValueT](
    values: Mapping[str, ValueT] | None = None,
) -> Mapping[str, ValueT]:
    return MappingProxyType(dict(values or {}))


def frozen_outcome(**values: object) -> Mapping[str, object]:
    return MappingProxyType(values)


def is_safe_integer(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER
    )


def iso_from_ms(value: int | float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DomainError("invalid_time")
    try:
        date = datetime.fromtimestamp(value / 1_000, tz=UTC)
    except (OSError, OverflowError, ValueError) as error:
        raise DomainError("invalid_time") from error
    return date.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def js_round(value: float) -> int:
    """Match JavaScript Math.round for the non-negative values used here."""

    return math.floor(value + 0.5)
