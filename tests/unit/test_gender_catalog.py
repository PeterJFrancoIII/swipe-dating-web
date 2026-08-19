from __future__ import annotations

from swipe_dating.domain.gender_catalog import (
    GENDER_CATALOG_REVIEWED,
    GENDER_CATALOG_SOURCES,
    GENDER_OPTIONS,
    MAX_GENDER_SELECTIONS,
    gender_labels,
    genders_are_compatible,
    normalize_gender_id,
    normalize_gender_identities,
)
from swipe_dating.domain.preferences import GENDER_IDENTITY_OPTIONS, choice_label


def test_gender_catalog_is_the_executable_source_of_truth() -> None:
    assert GENDER_CATALOG_REVIEWED == "2026-08-12"
    assert len(GENDER_CATALOG_SOURCES) >= 5
    assert len(GENDER_OPTIONS) == 29
    assert len(set(GENDER_OPTIONS)) == 29
    assert GENDER_IDENTITY_OPTIONS == GENDER_OPTIONS
    assert GENDER_OPTIONS[:3] == ("woman", "man", "non_binary")
    assert "agender" in GENDER_OPTIONS
    assert "two_spirit" in GENDER_OPTIONS
    assert "hijra" in GENDER_OPTIONS
    assert choice_label("non_binary") == "Non-binary"
    assert gender_labels(("woman", "agender")) == ("Woman", "Agender")


def test_legacy_and_current_gender_labels_normalize() -> None:
    assert normalize_gender_id("She") == "woman"
    assert normalize_gender_id("he") == "man"
    assert normalize_gender_id("nonbinary") == "non_binary"
    assert normalize_gender_id("Trans woman") == "trans_woman"
    assert normalize_gender_id("Two-Spirit") == "two_spirit"
    assert normalize_gender_identities(["woman", "woman", "agender", "nope"]) == (
        "woman",
        "agender",
    )
    assert len(normalize_gender_identities(GENDER_OPTIONS)) == MAX_GENDER_SELECTIONS
    assert len(normalize_gender_identities(GENDER_OPTIONS, limit=None)) == len(GENDER_OPTIONS)


def test_empty_gender_feed_shows_everyone() -> None:
    assert genders_are_compatible((), ("woman",))
    assert genders_are_compatible(("man",), ("man", "trans_man"))
    assert not genders_are_compatible(("man",), ("woman",))
