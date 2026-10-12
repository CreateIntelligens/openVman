"""視覺事件改問 Clef：一幀畫面＋每個事件一題是非題，直接拿機率。

Clef 是決策模型，不產生文字，回的是每題的機率；比起讓 VLM 吐 JSON 再解析，
不會有格式錯誤，也快得多（每張約 0.4 秒，VLM 約 1.3 秒）。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import get_tts_config
from app.gateway.plugins.vision_events import EVENT_DEFINITIONS
from app.http_client import SharedAsyncClient

logger = logging.getLogger("gateway.vision_clef")

_http = SharedAsyncClient(read=30)
_STATE = "這是虛擬人櫃台攝影機目前的畫面。"


def clef_enabled(cfg: Any = None) -> bool:
    cfg = cfg or get_tts_config()
    return bool((cfg.vision_clef_url or "").strip())


def _headers(cfg: Any) -> dict[str, str]:
    key = (getattr(cfg, "clef_api_key", "") or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


async def detect_events_with_clef(
    b64_data: str,
    mime_type: str,
    *,
    client: httpx.AsyncClient | None = None,
    cfg: Any = None,
) -> dict[str, bool]:
    """Return {event_key: bool}; raises on transport/format errors so callers can fall back."""
    cfg = cfg or get_tts_config()
    payload = {
        "model": cfg.vision_clef_model,
        "state": _STATE,
        # Clef 只收 data URL 字串；{content_type, base64} 物件會 422。
        "images": [f"data:{mime_type};base64,{b64_data}"],
        "questions": {
            event.key: {"type": "noul", "instructions": event.question}
            for event in EVENT_DEFINITIONS
        },
    }
    resp = await (client or _http.get()).post(
        cfg.vision_clef_url.strip(),
        json=payload,
        headers=_headers(cfg),
        timeout=cfg.vision_clef_timeout_seconds,
    )
    resp.raise_for_status()
    answers = resp.json().get("answers")
    if not isinstance(answers, dict):
        raise ValueError("Clef response is missing answers")
    result: dict[str, bool] = {}
    for event in EVENT_DEFINITIONS:
        answer = answers.get(event.key)
        probability = answer.get("noul") if isinstance(answer, dict) else None
        if isinstance(probability, bool) or not isinstance(probability, (int, float)):
            raise ValueError(f"Clef omitted a probability for {event.key!r}")
        result[event.key] = probability >= 0.5
    return result


async def probe_clef_health(
    client: httpx.AsyncClient | None = None,
    cfg: Any = None,
) -> dict[str, Any]:
    cfg = cfg or get_tts_config()
    if not clef_enabled(cfg):
        return {"status": "disabled", "route": "disabled", "model": cfg.vision_clef_model}
    parts = urlsplit(cfg.vision_clef_url.strip())
    health_url = f"{parts.scheme}://{parts.netloc}/health"
    try:
        resp = await (client or _http.get()).get(health_url, headers=_headers(cfg), timeout=3.0)
    except Exception as exc:
        return {"status": "unreachable", "route": "clef", "model": cfg.vision_clef_model, "error": str(exc)}
    if resp.status_code != 200:
        return {
            "status": "unreachable", "route": "clef", "model": cfg.vision_clef_model,
            "error": f"HTTP {resp.status_code}",
        }
    return {"status": "ready", "route": "clef", "model": cfg.vision_clef_model}
