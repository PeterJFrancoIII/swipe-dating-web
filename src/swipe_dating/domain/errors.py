"""Stable domain failures used by every adapter."""

from __future__ import annotations


class DomainError(ValueError):
    """A fail-closed product-rule error with a machine-readable code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)
