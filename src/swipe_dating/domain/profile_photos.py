"""Session-only profile photo rules. Images never enter the local R&D store."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
import pillow_heif
from PIL import Image, ImageOps

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.media_spec import (
    PROFILE_PHOTO_BIT_DEPTH,
    PROFILE_PHOTO_CONTENT_TYPE,
    PROFILE_PHOTO_LONG_EDGE_PX,
    PROFILE_PHOTO_MAX_BYTES,
    PROFILE_PHOTO_MAX_UPLOAD_BYTES,
    PROFILE_PHOTO_SHORT_EDGE_PX,
    PROFILE_PHOTO_SLOTS,
)

_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_WEBP_HEAD = b"RIFF"
_WEBP_MARK = b"WEBP"
_AVIF_BRANDS = frozenset({b"avif", b"avis"})
_HEIC_BRANDS = frozenset(
    {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"}
)
_HEIC_QUALITY_STEPS = (-1, 97, 94, 90, 86, 82, 78, 72)

__all__ = [
    "PROFILE_PHOTO_BIT_DEPTH",
    "PROFILE_PHOTO_CONTENT_TYPE",
    "PROFILE_PHOTO_LONG_EDGE_PX",
    "PROFILE_PHOTO_MAX_BYTES",
    "PROFILE_PHOTO_MAX_UPLOAD_BYTES",
    "PROFILE_PHOTO_SHORT_EDGE_PX",
    "PROFILE_PHOTO_SLOTS",
    "ProfilePhoto",
    "empty_profile_photos",
    "normalize_photo_slot",
    "parse_profile_photo",
    "prepare_profile_photo",
]


@dataclass(frozen=True, slots=True)
class ProfilePhoto:
    content_type: str
    payload: bytes
    display_content_type: str
    display_payload: bytes


def empty_profile_photos() -> tuple[ProfilePhoto | None, ...]:
    return (None,) * PROFILE_PHOTO_SLOTS


def normalize_photo_slot(slot: int) -> int:
    if slot not in range(PROFILE_PHOTO_SLOTS):
        raise DomainError("photo_slot_invalid")
    return slot


def prepare_profile_photo(payload: bytes) -> ProfilePhoto:
    if not payload:
        raise DomainError("photo_empty")
    if len(payload) > PROFILE_PHOTO_MAX_UPLOAD_BYTES:
        raise DomainError("photo_too_large")
    if _detect_image_type(payload) is None:
        raise DomainError("photo_type_unsupported")
    try:
        rgb = _fit_to_phone_raster(_rgb_from_payload(payload))
        heic, rgb = _encode_heic_under_limit(rgb)
        display_type, display_payload = _encode_display_image(rgb)
    except DomainError:
        raise
    except (OSError, SyntaxError, ValueError, TypeError) as error:
        raise DomainError("photo_type_unsupported") from error
    return ProfilePhoto(
        PROFILE_PHOTO_CONTENT_TYPE,
        heic,
        display_type,
        display_payload,
    )


def parse_profile_photo(payload: bytes) -> ProfilePhoto:
    return prepare_profile_photo(payload)


def _detect_image_type(payload: bytes) -> str | None:
    if payload.startswith(_JPEG):
        return "image/jpeg"
    if payload.startswith(_PNG):
        return "image/png"
    if len(payload) >= 12 and payload.startswith(_WEBP_HEAD) and payload[8:12] == _WEBP_MARK:
        return "image/webp"
    brands = _ftyp_brands(payload)
    if brands & _AVIF_BRANDS:
        return "image/avif"
    if brands & _HEIC_BRANDS:
        return "image/heic"
    return None


def _ftyp_brands(payload: bytes) -> set[bytes]:
    if len(payload) < 16 or payload[4:8] != b"ftyp":
        return set()
    declared = int.from_bytes(payload[:4], "big")
    box_end = declared if 16 <= declared <= len(payload) else min(len(payload), 256)
    brands = {payload[8:12]}
    for offset in range(16, box_end - 3, 4):
        brands.add(payload[offset : offset + 4])
    return brands


def _rgb_from_payload(payload: bytes) -> Image.Image:
    if _detect_image_type(payload) == "image/heic":
        return _rgb_from_heic(payload)
    image = Image.open(BytesIO(payload))
    image.load()
    oriented = ImageOps.exif_transpose(image)
    return (oriented if oriented is not None else image).convert("RGB")


def _rgb_from_heic(payload: bytes) -> Image.Image:
    source = pillow_heif.open_heif(payload, convert_hdr_to_8bit=True)
    pixels = np.asarray(source)
    if pixels.ndim == 2:
        pixels = np.stack((pixels, pixels, pixels), axis=2)
    if pixels.shape[2] > 3:
        pixels = pixels[:, :, :3]
    if pixels.dtype == np.uint16:
        pixels = (pixels // 257).astype(np.uint8)
    elif pixels.dtype != np.uint8:
        raise DomainError("photo_type_unsupported")
    return Image.fromarray(pixels)


def _fit_to_phone_raster(image: Image.Image) -> Image.Image:
    width, height = image.size
    long_edge = max(width, height)
    short_edge = min(width, height)
    scale = min(
        PROFILE_PHOTO_LONG_EDGE_PX / long_edge,
        PROFILE_PHOTO_SHORT_EDGE_PX / short_edge,
    )
    if scale >= 1:
        return image
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )


def _fit_long_edge(image: Image.Image, long_edge: int) -> Image.Image:
    width, height = image.size
    if max(width, height) <= long_edge:
        return image
    scale = long_edge / max(width, height)
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )


def _encode_heic_under_limit(image: Image.Image) -> tuple[bytes, Image.Image]:
    current = image
    for _attempt in range(8):
        for quality in _HEIC_QUALITY_STEPS:
            payload = _encode_heic(current, quality)
            if len(payload) <= PROFILE_PHOTO_MAX_BYTES:
                return payload, current
        width, height = current.size
        long_edge = max(width, height)
        if long_edge <= PROFILE_PHOTO_SHORT_EDGE_PX:
            break
        current = _fit_long_edge(
            current,
            max(PROFILE_PHOTO_SHORT_EDGE_PX, int(long_edge * 0.85)),
        )
    raise DomainError("photo_too_large")


def _encode_heic(image: Image.Image, quality: int) -> bytes:
    heif = pillow_heif.from_pillow(image.convert("RGB"))
    buffer = BytesIO()
    heif.save(
        buffer,
        quality=quality,
        chroma=444,
        matrix_coefficients=0 if quality < 0 else 6,
        color_primaries=12,
        transfer_characteristics=13,
    )
    return buffer.getvalue()


def _encode_display_image(image: Image.Image) -> tuple[str, bytes]:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="AVIF", quality=92, subsampling="4:4:4")
    payload = buffer.getvalue()
    if payload and len(payload) <= PROFILE_PHOTO_MAX_BYTES:
        return "image/avif", payload
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90, subsampling=0, optimize=True)
    jpeg = buffer.getvalue()
    if len(jpeg) > PROFILE_PHOTO_MAX_BYTES:
        raise DomainError("photo_too_large")
    return "image/jpeg", jpeg
