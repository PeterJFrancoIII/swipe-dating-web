"""Clearly labeled synthetic profiles and catalog fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from swipe_dating.domain.bot_moderation import CommunityMember
from swipe_dating.domain.discovery import (
    IMMEDIATE_INTENTS,
    RELATIONAL_OPENNESS,
    DiscoveryProfile,
)

GOLDEN_VIEWER: Final = DiscoveryProfile(
    id="viewer",
    immediate_intent="casual_dating",
    relational_openness="open_to_more",
    accepted_immediate_intents=("casual_dating", "friends_with_benefits"),
    accepted_relational_openness=("open_to_more", "relationship_possible"),
    boundaries=("condoms_required", "public_first_meet", "no_drugs"),
    required_boundaries=("condoms_required", "public_first_meet"),
    lifestyle_tags=("live_music", "hiking", "movie_night"),
    max_distance_km=40,
)

GOLDEN_CANDIDATE: Final = DiscoveryProfile(
    id="candidate-a",
    immediate_intent="friends_with_benefits",
    relational_openness="relationship_possible",
    accepted_immediate_intents=("casual_dating",),
    accepted_relational_openness=("open_to_more",),
    boundaries=("condoms_required", "public_first_meet", "no_drugs"),
    required_boundaries=("condoms_required",),
    lifestyle_tags=("live_music", "hiking"),
    alignment_score=84,
    distance_km=8,
)

LOCAL_VIEWER: Final = DiscoveryProfile(
    id="local-viewer",
    display_name="You",
    immediate_intent="casual_dating",
    relational_openness="open_to_more",
    accepted_immediate_intents=IMMEDIATE_INTENTS,
    accepted_relational_openness=RELATIONAL_OPENNESS,
    boundaries=("condoms_required", "public_first_meet", "no_drugs"),
    required_boundaries=("condoms_required", "public_first_meet", "no_drugs"),
    lifestyle_tags=("hiking", "movie_night", "live_music", "gaming"),
    max_distance_km=40,
)

SYNTHETIC_PROFILES: Final = (
    DiscoveryProfile(
        id="p1",
        display_name="Alex",
        age_band="24",
        about=("Coffee walks, tiny venues, climbing gyms, and making plans that actually happen."),
        immediate_intent="casual_dating",
        relational_openness="open_to_more",
        accepted_immediate_intents=(
            "casual_tonight",
            "friends_with_benefits",
            "casual_dating",
            "open_dating",
        ),
        accepted_relational_openness=(
            "casual_only",
            "open_to_more",
            "relationship_possible",
        ),
        boundaries=(
            "condoms_required",
            "recent_testing_discussion",
            "public_first_meet",
            "no_drugs",
        ),
        required_boundaries=("condoms_required", "public_first_meet"),
        lifestyle_tags=("coffee", "climbing", "live_music", "movie_night"),
        alignment_score=92,
        distance_km=4,
        synthetic_reciprocal_like=True,
    ),
    DiscoveryProfile(
        id="p2",
        display_name="Jordan",
        age_band="25",
        about=(
            "Trade work, pickup basketball, late-night food, and building things with my hands."
        ),
        immediate_intent="friends_with_benefits",
        relational_openness="relationship_possible",
        accepted_immediate_intents=(
            "friends_with_benefits",
            "casual_dating",
            "open_dating",
        ),
        accepted_relational_openness=(
            "open_to_more",
            "relationship_possible",
            "seeking_relationship",
        ),
        boundaries=(
            "condoms_required",
            "public_first_meet",
            "sober_meetup",
            "no_drugs",
        ),
        required_boundaries=("condoms_required",),
        lifestyle_tags=(
            "basketball",
            "live_music",
            "fitness",
            "building_things",
        ),
        alignment_score=81,
        distance_km=11,
        synthetic_reciprocal_like=False,
    ),
    DiscoveryProfile(
        id="p3",
        display_name="Morgan",
        age_band="23",
        about=("Museum afternoons, cooking experiments, co-op games, and very good playlists."),
        immediate_intent="open_dating",
        relational_openness="open_to_more",
        accepted_immediate_intents=(
            "casual_dating",
            "open_dating",
            "relationship_focused",
        ),
        accepted_relational_openness=(
            "open_to_more",
            "relationship_possible",
            "seeking_relationship",
        ),
        boundaries=(
            "condoms_required",
            "recent_testing_discussion",
            "public_first_meet",
            "no_smoking",
            "no_drugs",
        ),
        required_boundaries=("public_first_meet", "no_drugs"),
        lifestyle_tags=("museums", "cooking", "gaming", "movie_night"),
        alignment_score=95,
        distance_km=16,
        synthetic_reciprocal_like=True,
    ),
    DiscoveryProfile(
        id="p4",
        display_name="Riley",
        age_band="22",
        about=(
            "Sunday markets, film cameras, running by the river, and finding the best dumplings."
        ),
        immediate_intent="casual_dating",
        relational_openness="relationship_possible",
        accepted_immediate_intents=(
            "casual_dating",
            "open_dating",
            "relationship_focused",
        ),
        accepted_relational_openness=("open_to_more", "relationship_possible"),
        boundaries=("condoms_required", "public_first_meet", "no_drugs"),
        required_boundaries=("public_first_meet",),
        lifestyle_tags=("photography", "running", "food", "markets"),
        alignment_score=86,
        distance_km=9,
        synthetic_reciprocal_like=True,
    ),
    DiscoveryProfile(
        id="p5",
        display_name="Casey",
        age_band="24",
        about=(
            "Bookstores, indie games, ceramics, and a soft spot for aggressively specific trivia."
        ),
        immediate_intent="relationship_focused",
        relational_openness="seeking_relationship",
        accepted_immediate_intents=(
            "casual_dating",
            "relationship_focused",
            "figuring_it_out",
        ),
        accepted_relational_openness=(
            "open_to_more",
            "relationship_possible",
            "seeking_relationship",
        ),
        boundaries=(
            "condoms_required",
            "public_first_meet",
            "no_drugs",
            "no_smoking",
        ),
        required_boundaries=("public_first_meet", "no_drugs"),
        lifestyle_tags=("books", "gaming", "ceramics", "trivia"),
        alignment_score=88,
        distance_km=19,
        synthetic_reciprocal_like=False,
    ),
)

SYNTHETIC_COMMUNITY_MEMBERS: Final = (
    CommunityMember(
        id=LOCAL_VIEWER.id,
        adult_eligible=True,
        verified=False,
        account_age_days=30,
        good_standing=True,
        trust_cluster_id="local-browser",
    ),
    *(
        CommunityMember(
            id=f"reviewer-{index}",
            adult_eligible=True,
            verified=True,
            account_age_days=180 + index * 70,
            good_standing=True,
            trust_cluster_id=f"trusted-device-{index}",
        )
        for index in range(1, 8)
    ),
)

SYNTHETIC_BOT_SIGNALS: Final[Mapping[str, Mapping[str, object]]] = {
    "p1": {
        "adultCredentialValid": True,
        "attestation": "hardware_backed",
        "likesMinute": 2,
    },
    "p2": {
        "adultCredentialValid": True,
        "attestation": "software_fallback",
        "discoveryRequestsMinute": 180,
        "profileFetchesMinute": 150,
        "likesMinute": 90,
        "maliciousLinkHits24h": 1,
    },
    "p3": {
        "adultCredentialValid": True,
        "attestation": "hardware_backed",
        "likesMinute": 3,
    },
    "p4": {
        "adultCredentialValid": True,
        "attestation": "hardware_backed",
        "likesMinute": 1,
    },
    "p5": {
        "adultCredentialValid": True,
        "attestation": "hardware_backed",
        "likesMinute": 2,
    },
}

SYNTHETIC_BOT_TRUTH: Final[Mapping[str, bool]] = {
    "p1": False,
    "p2": True,
    "p3": False,
    "p4": False,
    "p5": False,
}

SKIN_ITEMS: Final = (
    ("neon-orbit", "Neon Orbit", "Profile skin", "$1.99 mock"),
    ("coffee-fox", "Coffee Fox", "Avatar", "Free mock"),
    ("midnight-chat", "Midnight Chat", "Chat skin", "$0.99 mock"),
)

QUESTIONNAIRE: Final = (
    (
        "political_alignment_importance",
        "How important is political alignment?",
        ("Not important", "Somewhat important", "Very important", "Dealbreaker"),
    ),
    (
        "education_path",
        "Which education or training path fits you?",
        ("College/university", "Trade/apprenticeship", "Self-taught", "A mix"),
    ),
    (
        "intimacy_style",
        "Which adult intimacy style sounds most compatible?",
        ("Mostly vanilla", "Adventurous", "Kink/BDSM-aware", "Depends on trust"),
    ),
)
