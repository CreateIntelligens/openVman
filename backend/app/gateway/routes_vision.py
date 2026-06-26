"""視覺輸入管道 — 把畫面用本地 VLM 轉成事件，僅在事件觸發時 ephemeral 餵給 AI（text 模式）。

攝影機是 AI 的眼睛。本端點供 text 模式使用：前端每秒推送一幀，
describe_frame 判斷是否有語意事件（人出現、物體消失等）。
只有事件邊緣才呼叫 brain chat，且以 ephemeral 方式注入視覺脈絡，不落歷史。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_tts_config
from app.gateway.plugins.camera_live import InvalidFrameError, decode_frame_base64
from app.gateway.worker import get_camera_plugin
from app.http_client import SharedAsyncClient

logger = logging.getLogger("gateway.routes.vision")

router = APIRouter(tags=["Vision"])

_http = SharedAsyncClient(read=30)


class VisionDescribeRequest(BaseModel):
    frame_base64: str = Field(..., min_length=1, description="Base64 JPEG frame")
    mime_type: str = Field("image/jpeg", description="Frame MIME type")
    timestamp: int = Field(0, ge=0)
    persona_id: str = Field("default")
    project_id: str = Field("default")
    session_id: str | None = Field(None)


@router.post("/api/vision/describe", summary="視覺事件（text 模式）")
async def vision_describe(payload: VisionDescribeRequest) -> dict[str, object]:
    try:
        image_bytes = decode_frame_base64(payload.frame_base64)
    except InvalidFrameError as exc:
        logger.warning("vision_describe_decode_err err=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_id = payload.session_id or ""
    result = await get_camera_plugin().describe_frame(
        image_bytes,
        payload.mime_type,
        session_id or "vision-text",
    )

    events = result.get("events") or []
    if result.get("status") != "processed" or not events:
        return {"reply": "", "session_id": session_id}

    context_text = str(events[0].get("context_text") or "").strip()
    if not context_text:
        return {"reply": "", "session_id": session_id}

    reply = await _generate_reply(payload, context_text)
    return {"reply": reply, "session_id": session_id}


async def _generate_reply(payload: VisionDescribeRequest, context_text: str) -> str:
    """把中性視覺脈絡當一則 ephemeral 訊息送進 brain chat（不落歷史），回傳 AI 回覆。"""
    cfg = get_tts_config()
    client = _http.get()
    try:
        resp = await client.post(
            f"{cfg.brain_url}/brain/chat",
            json={
                "message": context_text,
                "persona_id": payload.persona_id,
                "project_id": payload.project_id,
                "session_id": payload.session_id or "vision-text",
                "metadata": {"ephemeral_user_message": True},
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("vision_describe_reply_err err=%s", exc)
        return ""

    return str(data.get("reply") or "")
