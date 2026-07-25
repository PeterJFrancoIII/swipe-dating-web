from __future__ import annotations

import json
import stat
from pathlib import Path

from swipe_dating.adapters.storage import (
    JsonFileStorageAdapter,
    LocalStateRepository,
    MemoryStorageAdapter,
)
from swipe_dating.domain.local_state import create_default_local_state


def test_memory_repository_saves_loads_exports_and_clears() -> None:
    adapter = MemoryStorageAdapter()
    repository = LocalStateRepository(adapter)
    saved = repository.save(
        {
            "profile": {"displayName": "Avery", "about": "Local only", "pronouns": ""},
            "cosmetics": {
                "ownedSkinIds": ["neon-orbit"],
                "selectedSkinId": "neon-orbit",
            },
            "ui": {"hapticsEnabled": True, "lastTab": "My Profile"},
            "messages": ["must not persist"],
        },
        now_ms=1_753_185_600_000,
    )
    assert saved.state.profile.display_name == "Avery"
    assert '"schemaVersion":2' in adapter.inspect()
    assert "must not persist" not in adapter.inspect()
    assert repository.load().state.cosmetics.selected_skin_id == "neon-orbit"
    assert repository.export_text() == adapter.inspect()
    assert repository.clear() == create_default_local_state()
    assert adapter.inspect() is None


def test_json_file_repository_is_allowlisted_atomic_and_private(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "local-state.json"
    repository = LocalStateRepository(JsonFileStorageAdapter(path))
    repository.save(
        {
            "profile": {"displayName": "Riley", "about": "Builder", "pronouns": "they"},
            "ui": {"lastTab": "Matches", "hapticsEnabled": False},
            "birthDate": "2000-01-01",
            "matches": ["match:p1"],
            "messages": ["private"],
            "location": {"latitude": 1, "longitude": 2},
        },
        now_ms=0,
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"schemaVersion", "savedAt", "profile", "cosmetics", "ui"}
    assert raw["ui"]["lastTab"] == "Swipe"
    assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    assert not list(path.parent.glob("*.tmp"))


def test_json_file_invalid_content_recovers_and_clear_removes_file(tmp_path: Path) -> None:
    path = tmp_path / "local-state.json"
    path.write_text("{broken", encoding="utf-8")
    repository = LocalStateRepository(JsonFileStorageAdapter(path))
    loaded = repository.load()
    assert loaded.recovered and loaded.reason == "invalid_json"
    repository.clear()
    assert not path.exists()
