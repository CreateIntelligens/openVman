"""Built-in mascot catalog for the admin's right-corner assistant.

小助理只有內建的 Live2D Haru：不接受上傳，也不從人物衍生，因此沒有檔案儲存。
"""

from __future__ import annotations

from typing import Any

BUILTIN_MASCOTS: tuple[dict[str, Any], ...] = (
    {
        "mascot_id": "haru-live2d",
        "label": "Haru",
        "engine": "2d",
        "model_url": "https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/haru/haru_greeter_t03.model3.json",
        "thumbnail_url": "",
        "fit": "half",
        "builtin": True,
    },
)


def builtin_mascots() -> list[dict[str, Any]]:
    """Return copies so callers can annotate entries without touching the catalog."""
    return [dict(mascot) for mascot in BUILTIN_MASCOTS]
