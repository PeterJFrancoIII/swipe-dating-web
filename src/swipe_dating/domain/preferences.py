"""Private intent and filter policy constants."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

LOOKING_FOR_MODES: Final = (
    "long_term_relationship",
    "dating",
    "casual_sex",
    "group_encounter",
    "cuddles",
    "movie_night",
    "dinner_or_drinks",
    "concert_or_event",
    "gaming",
    "activity_partner",
    "sober_hangout",
    "conversation",
    "friends_first",
    "non_monogamous_connection",
    "figuring_it_out",
)

SEXUAL_INTENT_MODES: Final = frozenset({"casual_sex", "group_encounter"})

GENDER_DISCOVERY_CATEGORIES: Final = (
    "women",
    "men",
    "nonbinary_people",
    "additional_self_described_identities",
)

ALLOWED_FILTER_KEYS: Final = frozenset(
    {
        "activity_level",
        "fitness_lifestyle",
        "smoking_vaping",
        "alcohol_sober_lifestyle",
        "sleep_schedule",
        "education_path",
        "trade_path",
        "conversation_depth",
        "curiosity",
        "social_energy",
        "relationship_style",
        "adult_intimacy_interest",
        "body_hair_preference",
        "grooming_style",
        "fragrance_preference",
        "distance_band",
        "availability",
    }
)

PROHIBITED_FILTER_KEYS: Final = frozenset(
    {
        "race",
        "ethnicity",
        "skin_color",
        "disability",
        "height",
        "nationality_as_ethnicity_proxy",
        "inferred_attractiveness",
        "inferred_intelligence",
        "inferred_hygiene",
        "inferred_sexuality",
        "inferred_gender",
        "inferred_fitness",
        "inferred_grooming",
        "inferred_body_hair",
    }
)


def filter_key_allowed(key: str) -> bool:
    return key in ALLOWED_FILTER_KEYS and key not in PROHIBITED_FILTER_KEYS


def intents_are_compatible(left: Iterable[str], right: Iterable[str]) -> bool:
    return bool(set(left).intersection(right))
