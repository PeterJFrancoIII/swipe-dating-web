"""Memory and local-file adapters for the strict non-sensitive allowlist."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol

from swipe_dating.domain.local_state import (
    LOCAL_STATE_KEY,
    DeserializedLocalState,
    LocalState,
    create_default_local_state,
    deserialize_local_state,
    serialize_local_state,
)


class StorageAdapter(Protocol):
    def get_item(self, key: str) -> str | None: ...

    def set_item(self, key: str, value: str) -> None: ...

    def remove_item(self, key: str) -> None: ...


class MemoryStorageAdapter:
    def __init__(self, initial: str | None = None) -> None:
        self._values: dict[str, str] = {}
        if initial is not None:
            self._values[LOCAL_STATE_KEY] = initial

    def get_item(self, key: str) -> str | None:
        return self._values.get(key)

    def set_item(self, key: str, value: str) -> None:
        self._values[key] = value

    def remove_item(self, key: str) -> None:
        self._values.pop(key, None)

    def inspect(self, key: str = LOCAL_STATE_KEY) -> str | None:
        return self._values.get(key)


class JsonFileStorageAdapter:
    """One atomic JSON file. Content is allowlisted but deliberately unencrypted."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def get_item(self, key: str) -> str | None:
        del key
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def set_item(self, key: str, value: str) -> None:
        del key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                os.chmod(temporary_path, 0o600)
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    def remove_item(self, key: str) -> None:
        del key
        self.path.unlink(missing_ok=True)


class LocalStateRepository:
    def __init__(self, adapter: StorageAdapter, *, key: str = LOCAL_STATE_KEY) -> None:
        self._adapter = adapter
        self._key = key

    def load(self) -> DeserializedLocalState:
        return deserialize_local_state(self._adapter.get_item(self._key))

    def save(self, state: object, *, now_ms: int | float | None = None) -> DeserializedLocalState:
        text = serialize_local_state(state, now_ms=now_ms)
        self._adapter.set_item(self._key, text)
        return deserialize_local_state(text)

    def clear(self) -> LocalState:
        self._adapter.remove_item(self._key)
        return create_default_local_state()

    def export_text(self) -> str:
        return self._adapter.get_item(self._key) or serialize_local_state(
            create_default_local_state()
        )
