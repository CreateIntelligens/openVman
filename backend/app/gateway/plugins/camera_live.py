"""CameraLive plugin — periodic camera snapshot + Vision LLM."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import uuid
from typing import Any

import httpx

from app.config import get_tts_config
from app.gateway.forward import forward_to_brain

logger = logging.getLogger("gateway.plugin.camera_live")

INVALID_FRAME_MESSAGE = "影像資料格式錯誤"


class InvalidFrameError(ValueError):
    """Raised when a client-pushed frame is not valid base64."""


def decode_frame_base64(frame_base64: str) -> bytes:
    """Decode a base64 client frame, raising InvalidFrameError on bad input."""
    try:
        return base64.b64decode(frame_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidFrameError(INVALID_FRAME_MESSAGE) from exc


class CameraLivePlugin:
    """Captures periodic snapshots from a camera URL and describes them via Vision LLM."""

    id: str = "camera_live"

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._vision_client: Any = None
        self._vision_client_key: tuple[str, str] | None = None

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Start or query camera live stream for a session.

        params:
            session_id: str — required
            camera_url: str — required
            action: "start" | "stop" | "snapshot" (default "start")
        """
        session_id = params.get("session_id", "")
        camera_url = params.get("camera_url", "")
        action = params.get("action", "start")
        project_id = params.get("project_id", "default")
        persona_id = params.get("persona_id", "default")

        if action == "stop":
            await self.cleanup(session_id)
            return {"status": "stopped", "session_id": session_id}

        if action == "snapshot":
            result = await self._single_snapshot(camera_url, session_id)
            if _as_bool(params.get("forward", False)):
                result["forwarded"] = await self._forward_snapshot(
                    result,
                    camera_url=camera_url,
                    trace_id=str(params.get("trace_id") or _camera_trace_id()),
                    project_id=project_id,
                    persona_id=persona_id,
                )
            return result

        # action == "start"
        if session_id in self._tasks:
            return {"status": "already_running", "session_id": session_id}

        task = asyncio.create_task(self._snapshot_loop(camera_url, session_id, project_id, persona_id))
        self._tasks[session_id] = task
        return {"status": "started", "session_id": session_id}

    async def health_check(self) -> bool:
        return True

    async def cleanup(self, session_id: str) -> None:
        task = self._tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info("camera_cleanup session_id=%s", session_id)
        self._states.pop(session_id, None)

    async def describe_frame(
        self,
        image_bytes: bytes,
        mime_type: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Detect visual events on a frame; fire only on event edges.

        攝影機是 AI 的眼睛。本方法用 VLM 做結構化判讀，交給 per-session
        狀態機，只有事件邊緣（首次出現）才回報 events。busy 保護確保
        推理不排隊。
        """
        from app.gateway.plugins.vision_events import (
            detect_edges,
            format_fired_events,
        )

        state = self._state_for_session(session_id)
        if state["analyzing"]:
            return {"status": "busy", "session_id": session_id}

        state["analyzing"] = True
        try:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            detection = await self._detect_events(b64, mime_type)
            new_events_state, fired = detect_edges(state["events"], detection)
            state["events"] = new_events_state

            return {
                "status": "processed",
                "session_id": session_id,
                "events": format_fired_events(fired),
            }
        except Exception as exc:
            logger.warning("camera_describe_frame_err session_id=%s err=%s", session_id, exc)
            return {"status": "error", "session_id": session_id, "error": str(exc)}
        finally:
            state["analyzing"] = False

    async def _snapshot_loop(
        self,
        camera_url: str,
        session_id: str,
        project_id: str = "default",
        persona_id: str = "default",
    ) -> None:
        interval = get_tts_config().camera_snapshot_interval_sec
        self._state_for_session(session_id)

        while True:
            try:
                result = await self._single_snapshot(camera_url, session_id)
                forwarded = await self._forward_snapshot(
                    result,
                    camera_url=camera_url,
                    trace_id=_camera_trace_id(),
                    project_id=project_id,
                    persona_id=persona_id,
                )
                logger.info(
                    "camera_snapshot session_id=%s forwarded=%s",
                    session_id,
                    forwarded,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("camera_snapshot_err session_id=%s err=%s", session_id, exc)

            await asyncio.sleep(interval)

    async def _single_snapshot(self, camera_url: str, session_id: str) -> dict[str, Any]:
        """Fetch a single snapshot and describe it via Vision LLM."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(camera_url)
            resp.raise_for_status()
            image_bytes = resp.content

        content_type = resp.headers.get("content-type", "image/jpeg")

        return await self._analyze_image_bytes(image_bytes, content_type, session_id)

    async def _analyze_image_bytes(
        self,
        image_bytes: bytes,
        mime_type: str,
        session_id: str,
    ) -> dict[str, Any]:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        description = await self._describe_image(b64, mime_type)

        return {
            "type": "camera_snapshot",
            "session_id": session_id,
            "mime_type": mime_type,
            "description": description.strip(),
        }

    async def _forward_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        camera_url: str | None,
        trace_id: str,
        project_id: str,
        persona_id: str,
    ) -> bool:
        description = str(snapshot.get("description", "")).strip()
        if not description or "Vision LLM 未設定" in description:
            return False

        enriched_context = {
            "type": "camera_snapshot",
            "content": description,
            "source": self.id,
        }
        media_refs: list[dict[str, Any]] = []
        if camera_url:
            enriched_context["camera_url"] = camera_url
            media_refs.append({
                "camera_url": camera_url,
                "mime_type": str(snapshot.get("mime_type") or "image/jpeg"),
            })

        return await forward_to_brain(
            trace_id=trace_id,
            session_id=str(snapshot.get("session_id") or ""),
            enriched_context=[enriched_context],
            media_refs=media_refs,
            project_id=project_id,
            persona_id=persona_id,
        )

    def _get_vision_client(self) -> Any:
        """Return a pooled AsyncOpenAI client, rebuilt only when credentials change.

        Called once per frame on the hot path; constructing a new client each
        time would force a fresh connection pool + TLS handshake to the VLM.
        """
        from openai import AsyncOpenAI

        cfg = get_tts_config()
        if not cfg.vision_llm_api_key:
            return None

        key = (cfg.vision_llm_api_key, cfg.vision_llm_base_url or "")
        if self._vision_client is None or self._vision_client_key != key:
            client_kwargs: dict[str, Any] = {"api_key": cfg.vision_llm_api_key}
            if cfg.vision_llm_base_url:
                client_kwargs["base_url"] = cfg.vision_llm_base_url
            self._vision_client = AsyncOpenAI(**client_kwargs)
            self._vision_client_key = key
        return self._vision_client

    async def _complete_vision(self, prompt: str, b64_data: str, mime_type: str) -> str:
        """Single Vision LLM completion for a text prompt + one image."""
        client = self._get_vision_client()
        if client is None:
            return "（Vision LLM 未設定）"

        cfg = get_tts_config()
        response = await client.chat.completions.create(
            model=cfg.vision_llm_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                        },
                    ],
                }
            ],
            max_tokens=256,
        )
        return response.choices[0].message.content or ""

    async def _describe_image(self, b64_data: str, mime_type: str) -> str:
        """Call Vision LLM for a neutral description (legacy/snapshot path)."""
        prompt = (
            "你是數位虛擬人的「眼睛」。請用繁體中文簡短、客觀地描述這張畫面看到的內容："
            "有沒有人、人的大致外觀與動作、場景與物件。只做中性描述，"
            "不要給任何建議或指令，也不要決定要不要打招呼。"
        )
        return await self._complete_vision(prompt, b64_data, mime_type)

    async def _detect_events(self, b64_data: str, mime_type: str) -> dict[str, bool]:
        """Structured event detection: returns {event_key: bool} or {} on error."""
        from app.gateway.plugins.vision_events import (
            build_detection_prompt,
            parse_detection,
        )

        try:
            raw = await self._complete_vision(
                build_detection_prompt(),
                b64_data,
                mime_type,
            )
        except Exception as exc:
            logger.warning("vision_detect_events_err err=%s", exc)
            return {}
        return parse_detection(raw)

    def _state_for_session(self, session_id: str) -> dict[str, Any]:
        from app.gateway.plugins.vision_events import new_event_state

        existing = self._states.get(session_id)
        if existing is None:
            existing = {"analyzing": False, "events": new_event_state()}
            self._states[session_id] = existing
        elif "events" not in existing:
            existing["events"] = new_event_state()
        return existing


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _camera_trace_id() -> str:
    return f"camera-{uuid.uuid4().hex}"
