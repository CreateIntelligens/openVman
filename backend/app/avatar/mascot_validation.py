"""Validation for right-corner mascot uploads."""

import json
import re
import struct

_MASCOT_ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")
_GLB_MAGIC = b"glTF"


class InvalidMascotId(ValueError):
    """mascot_id 格式不合法。"""


class InvalidMascotUpload(ValueError):
    """吉祥物模型副檔名或內容不合法。"""


def normalize_mascot_id(mascot_id: str | None) -> str:
    text = (mascot_id or "").strip()
    if not _MASCOT_ID_RE.match(text):
        raise InvalidMascotId(
            "mascot_id 格式不合法（需以英數開頭結尾，中間可用 . _ -，長度 1-64）"
        )
    return text


def validate_vrm_bytes(data: bytes, *, filename: str) -> None:
    if not filename.lower().endswith(".vrm"):
        raise InvalidMascotUpload("模型必須是 .vrm 檔")
    if not data.startswith(_GLB_MAGIC):
        raise InvalidMascotUpload("模型內容不是有效的 VRM/GLB（glTF magic 不符）")


def extract_vrm_thumbnail(vrm_bytes: bytes) -> bytes | None:
    """Extract embedded thumbnail texture bytes from a VRM/GLB file.

    Supports both VRM 0.x and VRM 1.0 specifications.
    """
    if len(vrm_bytes) < 20:
        return None

    try:
        # Verify GLB Magic and version
        magic, version, _ = struct.unpack_from("<III", vrm_bytes, 0)
        if magic != 0x46546C67 or version != 2:
            return None

        # Read JSON chunk header
        chunk0_length, chunk0_type = struct.unpack_from("<II", vrm_bytes, 12)
        if chunk0_type != 0x4E4F534A:
            return None

        # Decode JSON metadata
        json_bytes = vrm_bytes[20 : 20 + chunk0_length]
        gltf = json.loads(json_bytes.decode("utf-8"))

        image_idx = None

        # Try VRM 0.x metadata path
        try:
            vrm_meta = gltf.get("extensions", {}).get("VRM", {}).get("meta", {})
            texture_idx = vrm_meta.get("texture")
            if texture_idx is not None:
                texture = gltf.get("textures", [])[texture_idx]
                image_idx = texture.get("source")
        except Exception:
            pass

        # Try VRM 1.0 metadata path
        if image_idx is None:
            try:
                vrm_meta = gltf.get("extensions", {}).get("VRMC_vrm", {}).get("meta", {})
                image_idx = vrm_meta.get("thumbnailImage")
            except Exception:
                pass

        if image_idx is None:
            return None

        # Locate image bufferView
        images = gltf.get("images", [])
        if image_idx >= len(images):
            return None
        image = images[image_idx]
        buffer_view_idx = image.get("bufferView")
        if buffer_view_idx is None:
            return None

        buffer_views = gltf.get("bufferViews", [])
        if buffer_view_idx >= len(buffer_views):
            return None
        buffer_view = buffer_views[buffer_view_idx]
        byte_offset = buffer_view.get("byteOffset", 0)
        byte_length = buffer_view.get("byteLength")
        if not byte_length:
            return None

        # Locate Chunk 1 (BIN)
        chunk1_offset = 20 + chunk0_length
        if chunk1_offset + 8 > len(vrm_bytes):
            return None

        chunk1_length, chunk1_type = struct.unpack_from("<II", vrm_bytes, chunk1_offset)
        if chunk1_type != 0x004E4942:
            return None

        bin_buffer_start = chunk1_offset + 8

        # Extract image slice
        img_start = bin_buffer_start + byte_offset
        img_end = img_start + byte_length
        if img_end > len(vrm_bytes):
            return None

        return vrm_bytes[img_start:img_end]
    except Exception:
        return None
