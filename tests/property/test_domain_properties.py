from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from swipe_dating.domain.discovery import normalize_ranking_weights
from swipe_dating.domain.local_state import sanitize_local_state, serialize_local_state


@given(
    st.dictionaries(
        st.sampled_from(("intent", "boundaries", "lifestyle", "alignment", "distance")),
        st.one_of(st.integers(-1_000, 1_000), st.floats(allow_nan=True), st.text(max_size=10)),
    )
)
def test_normalized_weights_always_total_one_hundred(values: dict[str, object]) -> None:
    normalized = normalize_ranking_weights(values)
    assert sum(normalized.values()) == 100
    assert all(0 <= value <= 100 for value in normalized.values())


@given(
    display_name=st.text(max_size=200),
    about=st.text(max_size=700),
    pronouns=st.text(max_size=100),
    skin_ids=st.lists(st.text(max_size=120), max_size=80),
)
def test_local_state_sanitizer_is_idempotent(
    display_name: str, about: str, pronouns: str, skin_ids: list[str]
) -> None:
    first = sanitize_local_state(
        {
            "profile": {
                "displayName": display_name,
                "about": about,
                "pronouns": pronouns,
            },
            "cosmetics": {"ownedSkinIds": skin_ids, "selectedSkinId": None},
            "ui": {"hapticsEnabled": True, "lastTab": "Swipe"},
        }
    )
    assert sanitize_local_state(first) == first
    serialized = json.loads(serialize_local_state(first, now_ms=0))
    assert set(serialized) == {"schemaVersion", "savedAt", "profile", "cosmetics", "ui"}


def test_local_state_sanitizer_trims_a_truncated_boundary() -> None:
    source = {
        "profile": {
            "displayName": "",
            "about": "",
            "pronouns": f"{'0' * 39} 0",
        },
        "cosmetics": {"ownedSkinIds": [], "selectedSkinId": None},
        "ui": {"hapticsEnabled": True, "lastTab": "Swipe"},
    }

    first = sanitize_local_state(source)

    assert first.profile.pronouns == "0" * 39
    assert sanitize_local_state(first) == first
