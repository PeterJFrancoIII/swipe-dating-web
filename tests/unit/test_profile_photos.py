from __future__ import annotations

from io import BytesIO

import numpy as np
import pillow_heif
import pytest
from PIL import Image

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.media_spec import (
    PROFILE_PHOTO_HEIGHT_PX,
    PROFILE_PHOTO_WIDTH_PX,
)
from swipe_dating.domain.profile_photos import (
    PROFILE_PHOTO_BIT_DEPTH,
    PROFILE_PHOTO_CONTENT_TYPE,
    PROFILE_PHOTO_LONG_EDGE_PX,
    PROFILE_PHOTO_MAX_BYTES,
    PROFILE_PHOTO_MAX_UPLOAD_BYTES,
    PROFILE_PHOTO_SHORT_EDGE_PX,
    PROFILE_PHOTO_SLOTS,
    empty_profile_photos,
    normalize_photo_slot,
    parse_profile_photo,
)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _png_bytes(width: int, height: int, *, compress_level: int = 6) -> bytes:
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(width, dtype=np.uint16) % 256
    pixels[:, :, 1] = np.arange(height, dtype=np.uint16)[:, None] % 256
    pixels[:, :, 2] = 90
    buffer = BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG", compress_level=compress_level)
    return buffer.getvalue()


def _encoded_bytes(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (40, 80, 120)).save(buffer, format=image_format)
    return buffer.getvalue()


def test_media_spec_matches_master_descriptor() -> None:
    assert PROFILE_PHOTO_WIDTH_PX == 1080
    assert PROFILE_PHOTO_HEIGHT_PX == 2400
    assert PROFILE_PHOTO_BIT_DEPTH == 8
    assert PROFILE_PHOTO_SLOTS == 6
    assert PROFILE_PHOTO_LONG_EDGE_PX == PROFILE_PHOTO_HEIGHT_PX
    assert PROFILE_PHOTO_SHORT_EDGE_PX == PROFILE_PHOTO_WIDTH_PX


def test_empty_profile_photos_has_six_open_slots() -> None:
    photos = empty_profile_photos()
    assert len(photos) == PROFILE_PHOTO_SLOTS
    assert all(photo is None for photo in photos)


def test_normalize_photo_slot_accepts_zero_through_five() -> None:
    assert tuple(normalize_photo_slot(slot) for slot in range(6)) == (0, 1, 2, 3, 4, 5)
    with pytest.raises(DomainError, match="photo_slot_invalid"):
        normalize_photo_slot(-1)
    with pytest.raises(DomainError, match="photo_slot_invalid"):
        normalize_photo_slot(6)


def test_parse_profile_photo_encodes_8bit_heif_and_rejects_unsafe_payloads() -> None:
    parsed = parse_profile_photo(PNG_1X1)
    assert parsed.content_type == PROFILE_PHOTO_CONTENT_TYPE
    assert parsed.display_content_type == "image/avif"
    heif = pillow_heif.open_heif(parsed.payload, convert_hdr_to_8bit=False)
    assert heif.info["bit_depth"] == PROFILE_PHOTO_BIT_DEPTH
    assert parsed.payload[4:8] == b"ftyp"
    assert parsed.display_payload[4:12] == b"ftypavif"
    assert len(parsed.payload) <= PROFILE_PHOTO_MAX_BYTES
    with pytest.raises(DomainError, match="photo_empty"):
        parse_profile_photo(b"")
    with pytest.raises(DomainError, match="photo_type_unsupported"):
        parse_profile_photo(b"not-an-image")
    with pytest.raises(DomainError, match="photo_too_large"):
        parse_profile_photo(b"\xff\xd8\xff" + b"\x00" * PROFILE_PHOTO_MAX_UPLOAD_BYTES)


def test_parse_profile_photo_accepts_jpeg_and_webp() -> None:
    jpeg = parse_profile_photo(_encoded_bytes("JPEG"))
    assert jpeg.content_type == PROFILE_PHOTO_CONTENT_TYPE
    webp = parse_profile_photo(_encoded_bytes("WEBP"))
    assert webp.content_type == PROFILE_PHOTO_CONTENT_TYPE


def test_oversized_original_is_resized_and_compressed_under_limit() -> None:
    original = _png_bytes(3200, 2400, compress_level=0)
    assert len(original) > PROFILE_PHOTO_MAX_BYTES
    parsed = parse_profile_photo(original)
    heif = pillow_heif.open_heif(parsed.payload, convert_hdr_to_8bit=False)
    assert max(heif.size) <= PROFILE_PHOTO_LONG_EDGE_PX
    assert min(heif.size) <= PROFILE_PHOTO_SHORT_EDGE_PX
    assert heif.info["bit_depth"] == PROFILE_PHOTO_BIT_DEPTH
    assert len(parsed.payload) <= PROFILE_PHOTO_MAX_BYTES
    assert len(parsed.display_payload) <= PROFILE_PHOTO_MAX_BYTES


def test_parse_profile_photo_accepts_heic_and_avif_outputs() -> None:
    first = parse_profile_photo(PNG_1X1)
    from_heic = parse_profile_photo(first.payload)
    from_avif = parse_profile_photo(first.display_payload)
    assert from_heic.content_type == PROFILE_PHOTO_CONTENT_TYPE
    assert from_avif.content_type == PROFILE_PHOTO_CONTENT_TYPE
    heif = pillow_heif.open_heif(from_heic.payload, convert_hdr_to_8bit=False)
    assert heif.info["bit_depth"] == PROFILE_PHOTO_BIT_DEPTH


def test_parse_profile_photo_rejects_truncated_jpeg() -> None:
    with pytest.raises(DomainError, match="photo_type_unsupported"):
        parse_profile_photo(b"\xff\xd8\xff" + b"\x00" * 32)
