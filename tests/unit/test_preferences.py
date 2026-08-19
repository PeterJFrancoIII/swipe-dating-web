from __future__ import annotations

from swipe_dating.domain.preferences import (
    choice_label,
    combined_profile_tags,
    sanitize_visibility,
    visibility_from_form,
)


def test_choice_labels_cover_common_profile_chips() -> None:
    assert choice_label("calm") == "Calm"
    assert choice_label("intense") == "Intense"
    assert choice_label("woman") == "Woman"
    assert choice_label("bdsm") == "BDSM"


def test_combined_profile_tags_keep_category_order_and_limit() -> None:
    tags = combined_profile_tags(
        ("coffee", "travel"),
        ("climbing",),
        ("calm", "intense"),
        limit=3,
    )
    assert tags == ("coffee", "travel", "climbing")


def test_card_visibility_defaults_and_form_round_trip() -> None:
    defaults = sanitize_visibility(None)
    assert defaults.photos is True
    assert defaults.bedroom is False
    hidden = visibility_from_form(("photos", "bedroom"), present=True)
    assert hidden.photos is True
    assert hidden.bedroom is True
    assert hidden.about is False
    assert visibility_from_form(None, present=False) == defaults
    assert sanitize_visibility({"about": False, "displayName": False}).display_name is False
