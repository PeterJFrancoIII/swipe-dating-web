from __future__ import annotations

import json

from swipe_dating.domain.local_state import (
    LOCAL_STATE_SCHEMA_VERSION,
    create_default_local_state,
    deserialize_local_state,
    sanitize_local_state,
    serialize_local_state,
)


def test_default_state_contains_only_approved_fields() -> None:
    assert create_default_local_state().to_dict() == {
        "profile": {"displayName": "", "about": "", "pronouns": ""},
        "cosmetics": {"ownedSkinIds": [], "selectedSkinId": None},
        "ui": {"hapticsEnabled": True, "lastTab": "Swipe"},
    }


def test_sanitization_truncates_deduplicates_and_excludes_matches_tab() -> None:
    sanitized = sanitize_local_state(
        {
            "profile": {
                "displayName": f"  {'x' * 100}  ",
                "about": " about ",
                "pronouns": " they/them ",
            },
            "cosmetics": {
                "ownedSkinIds": ["neon-orbit", "neon-orbit", ""],
                "selectedSkinId": "not-owned",
            },
            "ui": {"hapticsEnabled": False, "lastTab": "Matches"},
        }
    )
    assert len(sanitized.profile.display_name) == 64
    assert sanitized.profile.about == "about"
    assert sanitized.profile.pronouns == "they/them"
    assert sanitized.cosmetics.owned_skin_ids == ("neon-orbit",)
    assert sanitized.cosmetics.selected_skin_id is None
    assert sanitized.ui.last_tab == "Swipe"


def test_serialization_strips_all_sensitive_and_session_fields() -> None:
    raw_input = {
        "profile": {"displayName": "Riley", "about": "Builder", "pronouns": "they/them"},
        "cosmetics": {"ownedSkinIds": ["neon-orbit"], "selectedSkinId": "neon-orbit"},
        "ui": {"hapticsEnabled": True, "lastTab": "Swipe"},
        "activeTab": "Matches",
        "birthDate": "2000-01-01",
        "adultAccepted": True,
        "answers": {"politics": "private"},
        "selectedIntents": ["casual_sex"],
        "selectedGenders": ["women"],
        "immediateIntent": "casual_dating",
        "relationalOpenness": "open_to_more",
        "requiredBoundaries": ["condoms_required"],
        "discoveryWeights": {"intent": 50, "distance": 50},
        "conversationState": {"messages": ["private"]},
        "relationshipPhaseState": {"promptAnswers": {"x": "private"}},
        "matches": ["match:p1"],
        "messages": ["private"],
        "blockedCandidateIds": ["p3"],
        "locationChoice": "live_15_minutes",
        "encounterIds": ["secret"],
    }
    raw = json.loads(serialize_local_state(raw_input, now_ms=1_753_185_600_000))
    assert raw["schemaVersion"] == LOCAL_STATE_SCHEMA_VERSION
    assert raw["profile"]["displayName"] == "Riley"
    assert set(raw) == {"schemaVersion", "savedAt", "profile", "cosmetics", "ui"}


def test_v1_migration_invalid_json_and_future_schema_recover_safely() -> None:
    migrated = deserialize_local_state(
        json.dumps(
            {
                "schemaVersion": 1,
                "profileName": "Sam",
                "bio": "Hello",
                "pronouns": "she/her",
                "ownedSkins": ["neon-orbit"],
                "selectedSkin": "neon-orbit",
                "hapticsEnabled": False,
                "lastTab": "Skin Shop",
            }
        )
    )
    assert migrated.migrated_from == 1
    assert migrated.recovered is False
    assert migrated.state.profile.display_name == "Sam"
    assert migrated.state.cosmetics.selected_skin_id == "neon-orbit"

    invalid = deserialize_local_state("{broken")
    assert invalid.recovered and invalid.reason == "invalid_json"
    assert invalid.state == create_default_local_state()

    future = deserialize_local_state(json.dumps({"schemaVersion": 999}))
    assert future.recovered and future.reason == "unsupported_schema"
    assert future.migrated_from == 999


def test_empty_storage_is_a_clean_default_not_recovery() -> None:
    result = deserialize_local_state(None)
    assert result.state == create_default_local_state()
    assert result.recovered is False
    assert result.saved_at is None
