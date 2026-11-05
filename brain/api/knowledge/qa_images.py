"""Locate QA images and tell QR codes apart from ordinary pictures."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

from knowledge.workspace import ensure_workspace_scaffold

logger = logging.getLogger(__name__)

QA_IMAGE_MEDIA_TYPES = {
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".ico": "image/vnd.microsoft.icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
ALLOWED_QA_IMAGE_SUFFIXES = frozenset(QA_IMAGE_MEDIA_TYPES)
KIND_QR = "qr"
KIND_IMAGE = "image"
# 海報角落帶一個小 QR 的圖還是有內容可看：QR 要佔到這個比例才算「這張就是 QR」。
# 實測純 QR 約佔 0.4～0.6（旋轉後約 0.29），海報上的 QR 多在 0.12 以下。
QR_MIN_AREA_RATIO = 0.25

_cache_lock = threading.Lock()


def resolve_qa_image_path(image_id: str, project_id: str) -> Path | None:
    """Find an image by exact name, or by stem ignoring whitespace and case."""
    safe_id = Path(image_id).name
    if not safe_id or safe_id != image_id:
        return None
    images_dir = ensure_workspace_scaffold(project_id) / "knowledge" / ".qa_images"
    exact_path = images_dir / safe_id
    if exact_path.is_file() and exact_path.suffix.lower() in ALLOWED_QA_IMAGE_SUFFIXES:
        return exact_path
    if Path(safe_id).suffix:
        return None
    # 匯入來源的圖片名稱可能在括號前含空白（例如 PRP (1).jpg），
    # 但 CSV 的圖片 ID 是 PRP(1)。比對時忽略空白，避免同一資產因命名格式不同而找不到。
    normalized_id = re.sub(r"\s+", "", safe_id).casefold()
    candidates = sorted(images_dir.iterdir()) if images_dir.is_dir() else []
    for candidate in candidates:
        if (
            candidate.is_file()
            and re.sub(r"\s+", "", candidate.stem).casefold() == normalized_id
            and candidate.suffix.lower() in ALLOWED_QA_IMAGE_SUFFIXES
        ):
            return candidate
    return None


def classify_image(data: bytes) -> dict[str, Any]:
    """Classify image bytes; only a QR whose content can be read counts.

    只看「偵測到」不夠：實測 64 張圖裡有 10 張醫療插圖被偵測成 QR，但都解不出內容。
    """
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        # OpenCV 讀不了的格式（例如 AVIF）當一般圖片，也存起來，不必每次重試。
        return {"kind": KIND_IMAGE, "ratio": 0.0, "qr_payload": ""}
    payload, ratio = _read_qr(_to_gray(image))
    is_qr = bool(payload) and ratio >= QR_MIN_AREA_RATIO
    return {"kind": KIND_QR if is_qr else KIND_IMAGE, "ratio": ratio, "qr_payload": payload}


def _to_gray(image: Any) -> Any:
    import cv2
    import numpy as np

    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        # 透明背景直接讀會整張變黑，要先鋪白底。
        alpha = image[..., 3:4].astype(np.float32) / 255
        image = (image[..., :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _read_qr(gray: Any) -> tuple[str, float]:
    import cv2
    import numpy as np

    detector = cv2.QRCodeDetector()
    height, width = gray.shape
    attempts = [
        (gray, 1.0),
        (cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), 2.0),
        (cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA), 0.5),
        (255 - gray, 1.0),  # 反白的 QR
    ]
    for candidate, scale in attempts:
        try:
            payload, points, _ = detector.detectAndDecode(candidate)
        except cv2.error:
            continue
        if payload and points is not None:
            area = cv2.contourArea(points.reshape(-1, 2).astype(np.float32))
            return payload, round(area / (scale * scale * height * width), 3)
    return "", 0.0


def qa_image_kind(image_id: str, project_id: str) -> str | None:
    """Return the stored kind, classifying at most once per version of the file.

    判斷一張最慢約 0.8 秒，所以結果存檔，之後只查表。判斷不了時回 None，
    呼叫端當作不知道，照常顯示圖片，不讓這件事擋住回答。
    """
    try:
        path = resolve_qa_image_path(image_id, project_id)
        if path is None:
            return None
        stat = path.stat()
        with _cache_lock:
            cache = _load_cache(project_id)
            entry = cache.get(path.name)
            if _is_current(entry, stat):
                return entry["kind"]
            result = classify_image(path.read_bytes())
            cache[path.name] = {**result, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            _save_cache(project_id, cache, path.parent)
        return result["kind"]
    except Exception as exc:  # noqa: BLE001 - 分類失敗不能讓回答失敗
        logger.warning("qa_image_kind_failed image=%s error=%s", image_id, type(exc).__name__)
        return None


def _is_current(entry: Any, stat: os.stat_result) -> bool:
    return (
        isinstance(entry, dict)
        and entry.get("size") == stat.st_size
        and entry.get("mtime_ns") == stat.st_mtime_ns
        and entry.get("kind") in (KIND_QR, KIND_IMAGE)
    )


def _cache_path(project_id: str) -> Path:
    return ensure_workspace_scaffold(project_id) / "knowledge" / ".qa_image_kinds.json"


def _load_cache(project_id: str) -> dict[str, Any]:
    try:
        data = json.loads(_cache_path(project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(project_id: str, cache: dict[str, Any], images_dir: Path) -> None:
    live = {name: entry for name, entry in cache.items() if (images_dir / name).is_file()}
    target = _cache_path(project_id)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)
