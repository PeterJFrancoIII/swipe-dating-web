"""Transparent, advisory readiness for the existing local profile fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

MIN_PROFILE_ABOUT_CHARS: Final = 80
PROFILE_READINESS_ITEMS: Final = ("display_name", "about_context")


@dataclass(frozen=True, slots=True)
class ProfileReadiness:
    completed: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def completed_count(self) -> int:
        return len(self.completed)

    @property
    def total_count(self) -> int:
        return len(PROFILE_READINESS_ITEMS)

    @property
    def ready(self) -> bool:
        return not self.missing


def assess_profile_readiness(display_name: str, about: str) -> ProfileReadiness:
    """Check only whether the user supplied two explicit presentation basics."""
    checks = {
        "display_name": bool(display_name.strip()),
        "about_context": len(about.strip()) >= MIN_PROFILE_ABOUT_CHARS,
    }
    return ProfileReadiness(
        completed=tuple(item for item in PROFILE_READINESS_ITEMS if checks[item]),
        missing=tuple(item for item in PROFILE_READINESS_ITEMS if not checks[item]),
    )
