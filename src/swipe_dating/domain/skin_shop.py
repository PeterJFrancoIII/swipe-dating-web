"""Bounded declarative Skin Shop manifest validation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sized
from dataclasses import dataclass
from typing import Final, cast

from swipe_dating.domain.models import is_safe_integer

ALLOWED_SKIN_MIME_TYPES: Final = frozenset(
    {
        "image/png",
        "image/webp",
        "image/avif",
        "image/svg+xml;profile=swipe-safe-v1",
        "application/vnd.swipe.animation+json",
    }
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SkinValidation:
    valid: bool
    reasons: tuple[str, ...]


def validate_skin_manifest(manifest: Mapping[str, object] | None) -> SkinValidation:
    source = manifest or {}
    reasons: list[str] = []
    if not source.get("assetId") or not source.get("creatorId"):
        reasons.append("missing_identity")
    if source.get("mimeType") not in ALLOWED_SKIN_MIME_TYPES:
        reasons.append("mime_not_allowed")
    byte_length = source.get("byteLength")
    if not is_safe_integer(byte_length) or not 0 < cast(int, byte_length) <= 8 * 1024 * 1024:
        reasons.append("byte_limit")
    width = source.get("width")
    height = source.get("height")
    if not _bounded_integer(width, 4096) or not _bounded_integer(height, 4096):
        reasons.append("dimension_limit")
    if not _bounded_integer(source.get("frameCount"), 240):
        reasons.append("frame_limit")
    integrity = source.get("integritySha256")
    if not isinstance(integrity, str) or _SHA256.fullmatch(integrity) is None:
        reasons.append("invalid_integrity_hash")
    remote_references = source.get("remoteReferences", ())
    if isinstance(remote_references, Sized) and len(remote_references) > 0:
        reasons.append("remote_references_forbidden")
    return SkinValidation(not reasons, tuple(reasons))


def _bounded_integer(value: object, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum
