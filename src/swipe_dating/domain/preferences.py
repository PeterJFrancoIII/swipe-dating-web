"""Private intent and filter policy constants."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from swipe_dating.domain.gender_catalog import (
    GENDER_CHOICES,
    GENDER_OPTIONS,
    normalize_gender_id,
)

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

PROFILE_PHOTO_IDS: Final = ("p1", "p2", "p3", "p4", "p5")
GENDER_IDENTITY_OPTIONS: Final = GENDER_OPTIONS
GENDER_DISCOVERY_CATEGORIES: Final = GENDER_OPTIONS
INTEREST_CHOICES: Final = (
    ("music", "Music"),
    ("live_music", "Live music"),
    ("movie_night", "Movies"),
    ("movies_and_tv", "Movies & TV"),
    ("books", "Reading"),
    ("coffee", "Coffee"),
    ("food", "Food"),
    ("travel", "Travel"),
    ("fitness", "Fitness"),
    ("art", "Art"),
    ("fashion", "Fashion"),
    ("sports", "Sports"),
    ("tech", "Tech"),
    ("pets", "Pets"),
    ("outdoors", "Outdoors"),
    ("nightlife", "Nightlife"),
    ("wellness", "Wellness"),
    ("cars", "Cars"),
    ("volunteering", "Volunteering"),
    ("museums", "Museums"),
    ("trivia", "Trivia"),
    ("science", "Science"),
)
HOBBY_CHOICES: Final = (
    ("gym", "Gym"),
    ("running", "Running"),
    ("hiking", "Hiking"),
    ("climbing", "Climbing"),
    ("yoga", "Yoga"),
    ("cycling", "Cycling"),
    ("swimming", "Swimming"),
    ("camping", "Camping"),
    ("cooking", "Cooking"),
    ("baking", "Baking"),
    ("gaming", "Gaming"),
    ("board_games", "Board games"),
    ("photography", "Photography"),
    ("painting", "Painting"),
    ("writing", "Writing"),
    ("dancing", "Dancing"),
    ("concerts", "Concerts"),
    ("thrifting", "Thrifting"),
    ("gardening", "Gardening"),
    ("ceramics", "Ceramics"),
    ("markets", "Markets"),
    ("fishing", "Fishing"),
)
PERSONALITY_CHOICES: Final = (
    ("calm", "Calm"),
    ("intense", "Intense"),
    ("outgoing", "Outgoing"),
    ("introverted", "Introverted"),
    ("playful", "Playful"),
    ("serious", "Serious"),
    ("adventurous", "Adventurous"),
    ("homebody", "Homebody"),
    ("spontaneous", "Spontaneous"),
    ("planner", "Planner"),
    ("goofy", "Goofy"),
    ("thoughtful", "Thoughtful"),
    ("competitive", "Competitive"),
    ("easygoing", "Easygoing"),
    ("romantic", "Romantic"),
    ("independent", "Independent"),
    ("affectionate", "Affectionate"),
    ("direct", "Direct"),
)
INTEREST_OPTIONS: Final = tuple(value for value, _label in INTEREST_CHOICES)
HOBBY_OPTIONS: Final = tuple(value for value, _label in HOBBY_CHOICES)
PERSONALITY_OPTIONS: Final = tuple(value for value, _label in PERSONALITY_CHOICES)
BEDROOM_CHOICES: Final = (
    ("vanilla", "Vanilla"),
    ("curious", "Curious"),
    ("adventurous", "Adventurous"),
    ("sensual", "Sensual"),
    ("kink", "Kink"),
    ("bdsm", "BDSM"),
    ("dominant", "Dominant"),
    ("submissive", "Submissive"),
    ("switch", "Switch"),
    ("rope", "Rope"),
    ("impact", "Impact play"),
    ("role_play", "Role play"),
)
BEDROOM_OPTIONS: Final = tuple(value for value, _label in BEDROOM_CHOICES)
LIFESTYLE_TAG_OPTIONS: Final = INTEREST_OPTIONS
MAX_PROFILE_TAGS: Final = 5
MAX_LIFESTYLE_TAGS: Final = MAX_PROFILE_TAGS
PROFILE_VISIBILITY_FIELDS: Final = (
    "photos",
    "display_name",
    "age",
    "pronouns",
    "about",
    "looking_for",
    "interests",
    "hobbies",
    "personality",
    "bedroom",
)
VISIBILITY_JSON_KEYS: Final = {
    "photos": "photos",
    "display_name": "displayName",
    "age": "age",
    "pronouns": "pronouns",
    "about": "about",
    "looking_for": "lookingFor",
    "interests": "interests",
    "hobbies": "hobbies",
    "personality": "personality",
    "bedroom": "bedroom",
}


@dataclass(frozen=True, slots=True)
class ProfileVisibility:
    photos: bool = True
    display_name: bool = True
    age: bool = True
    pronouns: bool = True
    about: bool = True
    looking_for: bool = True
    interests: bool = True
    hobbies: bool = True
    personality: bool = True
    bedroom: bool = False

    def __getitem__(self, key: str) -> bool:
        if key not in PROFILE_VISIBILITY_FIELDS:
            raise KeyError(key)
        return bool(getattr(self, key))

    def to_json(self) -> dict[str, bool]:
        return {
            json_key: bool(getattr(self, field)) for field, json_key in VISIBILITY_JSON_KEYS.items()
        }


def sanitize_visibility(value: object) -> ProfileVisibility:
    source = value if isinstance(value, Mapping) else {}
    defaults = ProfileVisibility()
    kwargs: dict[str, bool] = {}
    for field, json_key in VISIBILITY_JSON_KEYS.items():
        raw = source.get(json_key)
        if raw is None:
            raw = source.get(field)
        kwargs[field] = raw if isinstance(raw, bool) else getattr(defaults, field)
    return ProfileVisibility(**kwargs)


def visibility_from_form(
    shown: Sequence[str] | None,
    *,
    present: bool,
) -> ProfileVisibility:
    if not present:
        return ProfileVisibility()
    selected = {item for item in (shown or ()) if item in PROFILE_VISIBILITY_FIELDS}
    return ProfileVisibility(**{field: field in selected for field in PROFILE_VISIBILITY_FIELDS})


CHOICE_LABELS: Final = {
    value: label
    for group in (
        GENDER_CHOICES,
        INTEREST_CHOICES,
        HOBBY_CHOICES,
        PERSONALITY_CHOICES,
        BEDROOM_CHOICES,
    )
    for value, label in group
}

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


def choice_label(value: str) -> str:
    return CHOICE_LABELS.get(value, value.replace("_", " "))


def normalize_gender_identity(value: str) -> str:
    return normalize_gender_id(value)


def combined_profile_tags(
    interests: tuple[str, ...],
    hobbies: tuple[str, ...],
    personality: tuple[str, ...],
    *,
    limit: int | None = None,
) -> tuple[str, ...]:
    tags = (*interests, *hobbies, *personality)
    return tags if limit is None else tags[:limit]
