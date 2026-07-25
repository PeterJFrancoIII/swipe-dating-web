from __future__ import annotations

from swipe_dating.domain.profile_readiness import (
    MIN_PROFILE_ABOUT_CHARS,
    assess_profile_readiness,
)


def test_profile_readiness_tracks_two_transparent_basics() -> None:
    empty = assess_profile_readiness("   ", "   ")
    assert empty.completed == ()
    assert empty.missing == ("display_name", "about_context")
    assert empty.completed_count == 0
    assert empty.total_count == 2
    assert empty.ready is False

    partial = assess_profile_readiness(" Riley ", "Short and honest")
    assert partial.completed == ("display_name",)
    assert partial.missing == ("about_context",)

    ready = assess_profile_readiness("Riley", "x" * MIN_PROFILE_ABOUT_CHARS)
    assert ready.completed == ("display_name", "about_context")
    assert ready.missing == ()
    assert ready.completed_count == ready.total_count
    assert ready.ready is True


def test_about_context_uses_trimmed_characters_at_the_exact_boundary() -> None:
    below = assess_profile_readiness("Riley", f" {'x' * (MIN_PROFILE_ABOUT_CHARS - 1)} ")
    exact = assess_profile_readiness("Riley", f" {'x' * MIN_PROFILE_ABOUT_CHARS} ")

    assert "about_context" in below.missing
    assert "about_context" in exact.completed
