"""Canonical media constraints. Keep in lockstep with docs/MASTER_DESCRIPTOR.md."""

from __future__ import annotations

from typing import Final

# FHD+ (1080 x 2400): dominant smartphone panel class by shipment.
PROFILE_PHOTO_WIDTH_PX: Final = 1080
PROFILE_PHOTO_HEIGHT_PX: Final = 2400
PROFILE_PHOTO_LONG_EDGE_PX: Final = PROFILE_PHOTO_HEIGHT_PX
PROFILE_PHOTO_SHORT_EDGE_PX: Final = PROFILE_PHOTO_WIDTH_PX
# 8-bit/channel is the volume-majority phone still and display pipeline.
PROFILE_PHOTO_BIT_DEPTH: Final = 8
PROFILE_PHOTO_SLOTS: Final = 6
PROFILE_PHOTO_MAX_BYTES: Final = 5 * 1024 * 1024
PROFILE_PHOTO_MAX_UPLOAD_BYTES: Final = 40 * 1024 * 1024
PROFILE_PHOTO_CONTENT_TYPE: Final = "image/heic"
