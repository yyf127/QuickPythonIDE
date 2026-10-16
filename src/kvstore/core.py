"""JSON-backed key-value store.

A small, dependency-free persistence layer that stores arbitrary JSON-serialisable
values in a single JSON file. Safe to instantiate repeatedly against the same path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class KVStore:
    """A key-value store persisted to a JSON file."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key`` and persist immediately."""
        self._data[key] = value
        self._save()

    def get(self, key: str) -> Any:
        """Return the value for ``key`` or raise ``KeyError`` if missing."""
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def delete(self, key: str) -> bool:
        """Delete ``key``. Return ``True`` if it existed, ``False`` otherwise."""
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False

    def list(self) -> dict[str, Any]:
        """Return a shallow copy of all stored key-value pairs."""
        return dict(self._data)
