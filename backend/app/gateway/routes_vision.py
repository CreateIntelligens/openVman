"""視覺輸入管道 — 把畫面用 Clef（備援 VLM）轉成事件，僅在事件觸發時 ephemeral 餵給 AI（text 模式）。

攝影機是 AI 的眼睛。本端點供 text 模式使用：前端每秒推送一幀，
describe_frame 判斷是否有語意事件（人出現、物體消失等）。
只有事件邊緣才呼叫 brain chat，且以 ephemeral 方式注入視覺脈絡，不落歷史。
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.models import ResourceType
from app.auth.resources import ResourceNotFoundError, resolve_resource
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.config import get_tts_config
from app.gateway.plugins.camera_live import InvalidFrameError, decode_frame_base64
from app.gateway.vision_clef import probe_clef_health
from app.gateway.vlm_client import probe_vlm_health
from app.gateway.worker import get_camera_plugin
from app.http_client import SharedAsyncClient
from app.utils.images import validate_image
from app.utils.upload import UploadLimitError, UploadTooLargeError, as_http_exception

logger = logging.getLogger("gateway.routes.vision")

router = APIRouter(tags=["Vision"])

_http = SharedAsyncClient(read=30)


def _vision_session_id(session_id: str | None) -> str:
    return (session_id or "").strip() or f"vision-{uuid4().hex}"


class VisionDescribeRequest(BaseModel):
    frame_base64: str = Field(
        ...,
        min_length=1,
        description="Base64 影格（JPEG／PNG／WebP），解碼後上限 VISION_FRAME_MAX_BYTES（預設 10 MB）",
    )
    mime_type: str = Field(
        "image/jpeg",
        description="僅供參考；實際格式依解碼後的 magic bytes 判斷",
    )
    timestamp: int = Field(0, ge=0)
    persona_id: str = Field("default")
    project_id: str = Field("default")
    session_id: str | None = Field(None)


class VisionResetRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


@router.post("/api/v1/vision/describe", summary="視覺事件（text 模式）")
async def vision_describe(
    payload: VisionDescribeRequest,
    current: CurrentAccount = Depends(get_current_account),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> dict[str, object]:
    try:
        resolve_resource(
            runtime.resources,
            current.user,
            ResourceType.PROJECT,
            payload.project_id,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resource not found") from exc
    cfg = get_tts_config()
    max_bytes = cfg.vision_frame_max_bytes
    # base64 每 3 bytes 變 4 個字元；先看字串長度，超過就不必解碼。
    if len(payload.frame_base64) > (max_bytes + 2) // 3 * 4:
        raise as_http_exception(UploadTooLargeError(max_bytes, label="影格"))
    try:
        image_bytes = decode_frame_base64(payload.frame_base64)
    except InvalidFrameError as exc:
        logger.warning("vision_describe_decode_err err=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        if len(image_bytes) > max_bytes:
            raise UploadTooLargeError(max_bytes, label="影格")
        # 用者自報的 mime_type 不可信；送給判讀服務的是實際格式。
        mime_type = validate_image(image_bytes, max_side=cfg.upload_image_max_side_px)
    except UploadLimitError as exc:
        raise as_http_exception(exc) from exc

    session_id = _vision_session_id(payload.session_id)
    result = await get_camera_plugin().describe_frame(
        image_bytes,
        mime_type,
        session_id,
    )

    visual_state = result.get("visual_state")
    events = result.get("events") or []
    if result.get("status") != "processed" or not events:
        return {"reply": "", "session_id": session_id, "visual_state": visual_state}

    context_text = str(events[0].get("context_text") or "").strip()
    if not context_text:
        return {"reply": "", "session_id": session_id, "visual_state": visual_state}

    reply = await _generate_reply(
        payload,
        context_text,
        session_id,
        current,
    )
    return {"reply": reply, "session_id": session_id, "visual_state": visual_state}


@router.get("/api/v1/vision/health", summary="視覺管道健康狀態")
async def vision_health() -> dict[str, object]:
    """回報視覺判讀可用性（Clef 優先、VLM 備援），供前端決定是否開放攝影機 UI。"""
    cfg = get_tts_config()
    probe = await probe_clef_health(client=_http.get(), cfg=cfg)
    if probe.get("status") != "ready":
        vlm_probe = await probe_vlm_health(client=_http.get(), cfg=cfg)
        if vlm_probe.get("status") != "disabled" or probe.get("status") == "disabled":
            probe = vlm_probe
    status = str(probe.get("status", "unknown"))
    return {
        "available": status == "ready",
        "status": status,
        "route": probe.get("route", ""),
        "model": probe.get("model", ""),
    }


@router.post("/api/v1/vision/reset", summary="重置視覺事件狀態（text 模式）")
async def vision_reset(payload: VisionResetRequest) -> dict[str, object]:
    session_id = payload.session_id.strip()
    camera = get_camera_plugin()
    camera.reset_session_events(session_id)
    return {
        "status": "reset",
        "session_id": session_id,
        "visual_state": camera.session_visual_state(session_id),
    }


async def _generate_reply(
    payload: VisionDescribeRequest,
    context_text: str,
    session_id: str,
    current: CurrentAccount,
) -> str:
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
                "session_id": session_id,
                "metadata": {"ephemeral_user_message": True},
            },
            headers={
                "X-Internal-Token": cfg.gateway_internal_token,
                "X-OpenVMan-User-ID": current.user.id,
                "X-OpenVMan-Role": current.user.role.value,
                "X-OpenVMan-Project-ID": payload.project_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("vision_describe_reply_err err=%s", exc)
        return ""

    return str(data.get("reply") or "")
