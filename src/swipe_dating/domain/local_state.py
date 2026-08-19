"""Executable allowlist for the unencrypted local R&D profile file."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from swipe_dating.domain.gender_catalog import normalize_gender_identities
from swipe_dating.domain.models import iso_from_ms
from swipe_dating.domain.preferences import (
    BEDROOM_OPTIONS,
    HOBBY_OPTIONS,
    INTEREST_OPTIONS,
    MAX_PROFILE_TAGS,
    PERSONALITY_OPTIONS,
    PROFILE_PHOTO_IDS,
    ProfileVisibility,
    sanitize_visibility,
)

LOCAL_STATE_KEY: Final = "@swipe/rnd/local-state"
LOCAL_STATE_SCHEMA_VERSION: Final = 2
ALLOWED_TABS: Final = frozenset({"Swipe"})


@dataclass(frozen=True, slots=True)
class LocalProfile:
    display_name: str = ""
    about: str = ""
    pronouns: str = ""
    gender_identities: tuple[str, ...] = ()
    photo_id: str = ""
    lifestyle_tags: tuple[str, ...] = ()
    hobby_tags: tuple[str, ...] = ()
    personality_tags: tuple[str, ...] = ()
    bedroom_tags: tuple[str, ...] = ()
    visibility: ProfileVisibility = field(default_factory=ProfileVisibility)


@dataclass(frozen=True, slots=True)
class LocalCosmetics:
    owned_skin_ids: tuple[str, ...] = ()
    selected_skin_id: str | None = None


@dataclass(frozen=True, slots=True)
class LocalUi:
    haptics_enabled: bool = True
    last_tab: str = "Swipe"


@dataclass(frozen=True, slots=True)
class LocalState:
    profile: LocalProfile = LocalProfile()
    cosmetics: LocalCosmetics = LocalCosmetics()
    ui: LocalUi = LocalUi()

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": {
                "displayName": self.profile.display_name,
                "about": self.profile.about,
                "pronouns": self.profile.pronouns,
                "genderIdentities": list(self.profile.gender_identities),
                "photoId": self.profile.photo_id,
                "lifestyleTags": list(self.profile.lifestyle_tags),
                "hobbyTags": list(self.profile.hobby_tags),
                "personalityTags": list(self.profile.personality_tags),
                "bedroomTags": list(self.profile.bedroom_tags),
                "cardVisibility": self.profile.visibility.to_json(),
            },
            "cosmetics": {
                "ownedSkinIds": list(self.cosmetics.owned_skin_ids),
                "selectedSkinId": self.cosmetics.selected_skin_id,
            },
            "ui": {
                "hapticsEnabled": self.ui.haptics_enabled,
                "lastTab": self.ui.last_tab,
            },
        }


@dataclass(frozen=True, slots=True)
class MigrationResult:
    state: LocalState
    migrated_from: int | None
    recovered: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class DeserializedLocalState:
    state: LocalState
    saved_at: str | None
    migrated_from: int | None
    recovered: bool
    reason: str | None


def create_default_local_state() -> LocalState:
    return LocalState()


def sanitize_local_state(value: object) -> LocalState:
    source = _as_mapping(value)
    profile = _as_mapping(source.get("profile"))
    cosmetics = _as_mapping(source.get("cosmetics"))
    ui = _as_mapping(source.get("ui"))
    owned_skin_ids = _unique_strings(cosmetics.get("ownedSkinIds"), 50, 80)
    selected_skin_id = _clean_string(cosmetics.get("selectedSkinId"), 80) or None
    haptics_enabled = ui.get("hapticsEnabled")
    return LocalState(
        profile=LocalProfile(
            display_name=_clean_string(profile.get("displayName"), 64),
            about=_clean_string(profile.get("about"), 500),
            pronouns=_clean_string(profile.get("pronouns"), 40),
            gender_identities=_gender_identities_from(profile),
            photo_id=_allowed_choice(profile.get("photoId"), PROFILE_PHOTO_IDS),
            lifestyle_tags=_allowed_tags(
                profile.get("lifestyleTags"),
                INTEREST_OPTIONS,
                MAX_PROFILE_TAGS,
            ),
            hobby_tags=_allowed_tags(
                profile.get("hobbyTags"),
                HOBBY_OPTIONS,
                MAX_PROFILE_TAGS,
            ),
            personality_tags=_allowed_tags(
                profile.get("personalityTags"),
                PERSONALITY_OPTIONS,
                MAX_PROFILE_TAGS,
            ),
            bedroom_tags=_allowed_tags(
                profile.get("bedroomTags"),
                BEDROOM_OPTIONS,
                MAX_PROFILE_TAGS,
            ),
            visibility=sanitize_visibility(profile.get("cardVisibility")),
        ),
        cosmetics=LocalCosmetics(
            owned_skin_ids=owned_skin_ids,
            selected_skin_id=(selected_skin_id if selected_skin_id in owned_skin_ids else None),
        ),
        ui=LocalUi(
            haptics_enabled=haptics_enabled if isinstance(haptics_enabled, bool) else True,
            last_tab=(str(ui["lastTab"]) if ui.get("lastTab") in ALLOWED_TABS else "Swipe"),
        ),
    )


def migrate_local_state(value: object) -> MigrationResult:
    raw = _as_mapping(value)
    if not isinstance(value, Mapping):
        return MigrationResult(create_default_local_state(), None, True, "invalid_shape")
    schema_version = raw.get("schemaVersion")
    if type(schema_version) is int and schema_version == LOCAL_STATE_SCHEMA_VERSION:
        return MigrationResult(sanitize_local_state(raw), None, False, None)
    if type(schema_version) is int and schema_version == 1:
        state = sanitize_local_state(
            {
                "profile": {
                    "displayName": raw.get("profileName"),
                    "about": raw.get("bio"),
                    "pronouns": raw.get("pronouns"),
                },
                "cosmetics": {
                    "ownedSkinIds": raw.get("ownedSkins"),
                    "selectedSkinId": raw.get("selectedSkin"),
                },
                "ui": {
                    "hapticsEnabled": raw.get("hapticsEnabled"),
                    "lastTab": raw.get("lastTab"),
                },
            }
        )
        return MigrationResult(state, 1, False, None)
    migrated_from = schema_version if type(schema_version) is int else None
    return MigrationResult(create_default_local_state(), migrated_from, True, "unsupported_schema")


def serialize_local_state(value: object, *, now_ms: int | float | None = None) -> str:
    state = sanitize_local_state(value)
    payload = {
        "schemaVersion": LOCAL_STATE_SCHEMA_VERSION,
        "savedAt": iso_from_ms(time.time() * 1_000 if now_ms is None else now_ms),
        **state.to_dict(),
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def deserialize_local_state(text: str | None) -> DeserializedLocalState:
    if not isinstance(text, str) or not text:
        return DeserializedLocalState(create_default_local_state(), None, None, False, None)
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return DeserializedLocalState(
            create_default_local_state(), None, None, True, "invalid_json"
        )
    migrated = migrate_local_state(raw)
    saved_at = raw.get("savedAt") if isinstance(raw, Mapping) else None
    return DeserializedLocalState(
        state=migrated.state,
        saved_at=saved_at if isinstance(saved_at, str) else None,
        migrated_from=migrated.migrated_from,
        recovered=migrated.recovered,
        reason=migrated.reason,
    )


def _gender_identities_from(profile: Mapping[str, object]) -> tuple[str, ...]:
    raw = profile.get("genderIdentities")
    if raw is None:
        raw = profile.get("genderIdentity")
    return normalize_gender_identities(raw)


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, LocalState):
        return value.to_dict()
    if isinstance(value, Mapping):
        return value
    return {}


def _clean_string(value: object, max_length: int) -> str:
    return value.strip()[:max_length].rstrip() if isinstance(value, str) else ""


def _allowed_choice(value: object, allowed: tuple[str, ...]) -> str:
    cleaned = _clean_string(value, 40)
    return cleaned if cleaned in allowed else ""


def _allowed_tags(value: object, allowed: tuple[str, ...], max_items: int) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    allowed_set = set(allowed)
    result: list[str] = []
    for entry in value:
        cleaned = _clean_string(entry, 40)
        if cleaned in allowed_set and cleaned not in result:
            result.append(cleaned)
        if len(result) >= max_items:
            break
    return tuple(result)


def _unique_strings(value: object, max_items: int, max_length: int) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    result: list[str] = []
    for entry in value:
        cleaned = _clean_string(entry, max_length)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= max_items:
            break
    return tuple(result)
