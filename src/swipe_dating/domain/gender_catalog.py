"""Canonical gender catalog. Keep in lockstep with docs/MASTER_DESCRIPTOR.md.

This list is living. Re-check the cited sources whenever this file is edited, and at
least once per calendar quarter. Update GENDER_CATALOG_REVIEWED even when labels
do not change. If the descriptor and this file disagree, the descriptor wins.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final

GENDER_CATALOG_REVIEWED: Final = "2026-08-12"
GENDER_CATALOG_SOURCES: Final = (
    "https://glaad.org/reference/trans-terms/",
    "https://glaad.org/reference/terms/",
    "https://okcupid-app.zendesk.com/hc/en-us/articles/23546564004507-Gender-and-Orientation-on-OkCupid",
    "https://bumble.com/en-us/the-buzz/bumble-gender-options",
    "https://www.help.tinder.com/hc/en-us/articles/15668360470669-Gender-Sexual-Orientation",
    "https://help.hinge.co/hc/en-us/articles/4407404339603-How-did-Hinge-decide-which-gender-options-to-include",
)
MAX_GENDER_SELECTIONS: Final = 5

# Deduplicated union of current dating-app lists (OkCupid 22, Bumble detail,
# Tinder/Hinge/Grindr umbrellas), following GLAAD on deprecated synonyms.
GENDER_CHOICES: Final = (
    ("woman", "Woman"),
    ("man", "Man"),
    ("non_binary", "Non-binary"),
    ("cis_woman", "Cis woman"),
    ("cis_man", "Cis man"),
    ("trans_woman", "Trans woman"),
    ("trans_man", "Trans man"),
    ("transfeminine", "Transfeminine"),
    ("transmasculine", "Transmasculine"),
    ("transgender", "Transgender"),
    ("agender", "Agender"),
    ("androgynous", "Androgynous"),
    ("bigender", "Bigender"),
    ("genderfluid", "Genderfluid"),
    ("genderqueer", "Genderqueer"),
    ("gender_nonconforming", "Gender nonconforming"),
    ("gender_questioning", "Gender questioning"),
    ("neutrois", "Neutrois"),
    ("pangender", "Pangender"),
    ("polygender", "Polygender"),
    ("demiboy", "Demiboy"),
    ("demigirl", "Demigirl"),
    ("non_binary_woman", "Non-binary woman"),
    ("non_binary_man", "Non-binary man"),
    ("intersex", "Intersex"),
    ("intersex_woman", "Intersex woman"),
    ("intersex_man", "Intersex man"),
    ("two_spirit", "Two-Spirit"),
    ("hijra", "Hijra"),
)
GENDER_OPTIONS: Final = tuple(value for value, _label in GENDER_CHOICES)
GENDER_LABELS: Final = dict(GENDER_CHOICES)
GENDER_DISCOVERY_CATEGORIES: Final = GENDER_OPTIONS

_GENDER_ALIASES: Final = {
    "he": "man",
    "she": "woman",
    "other": "non_binary",
    "nonbinary": "non_binary",
    "non-binary": "non_binary",
    "cis woman": "cis_woman",
    "cis man": "cis_man",
    "cisgender woman": "cis_woman",
    "cisgender man": "cis_man",
    "trans woman": "trans_woman",
    "trans man": "trans_man",
    "transgender woman": "trans_woman",
    "transgender man": "trans_man",
    "gender fluid": "genderfluid",
    "gender-fluid": "genderfluid",
    "gender nonconforming": "gender_nonconforming",
    "gender non-conforming": "gender_nonconforming",
    "gender questioning": "gender_questioning",
    "non-binary woman": "non_binary_woman",
    "non-binary man": "non_binary_man",
    "intersex woman": "intersex_woman",
    "intersex man": "intersex_man",
    "two spirit": "two_spirit",
    "two-spirit": "two_spirit",
}


def normalize_gender_id(value: str) -> str:
    stripped = value.strip().lower()
    if stripped in GENDER_LABELS:
        return stripped
    dashed = stripped.replace(" ", "_").replace("-", "_")
    if dashed in GENDER_LABELS:
        return dashed
    return _GENDER_ALIASES.get(stripped, _GENDER_ALIASES.get(dashed, ""))


def normalize_gender_identities(
    values: object,
    *,
    limit: int | None = MAX_GENDER_SELECTIONS,
) -> tuple[str, ...]:
    if isinstance(values, str):
        items: tuple[object, ...] = (values,)
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray)):
        items = tuple(values)
    else:
        return ()
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        gender = normalize_gender_id(item)
        if gender and gender not in result:
            result.append(gender)
        if limit is not None and len(result) >= limit:
            break
    return tuple(result)


def gender_labels(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(GENDER_LABELS[value] for value in values if value in GENDER_LABELS)


def genders_are_compatible(feed: Iterable[str], candidate: Iterable[str]) -> bool:
    wanted = set(feed)
    if not wanted:
        return True
    return bool(wanted.intersection(candidate))
