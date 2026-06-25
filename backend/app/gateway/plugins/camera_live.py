"""CameraLive plugin — periodic camera snapshot + Vision LLM."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any

import httpx

from app.config import get_tts_config
from app.gateway.forward import forward_to_brain

logger = logging.getLogger("gateway.plugin.camera_live")

_UNKNOWN = "不確定"


class CameraLivePlugin:
    """Captures periodic snapshots from a camera URL and describes them via Vision LLM."""

    id: str = "camera_live"

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._states: dict[str, dict[str, Any]] = {}

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

    async def _snapshot_loop(
        self,
        camera_url: str,
        session_id: str,
        project_id: str = "default",
        persona_id: str = "default",
    ) -> None:
        interval = get_tts_config().camera_snapshot_interval_sec

        state = self._states[session_id] = {
            "consecutive_person_frames": 0,
            "consecutive_empty_frames": 0,
            "greeted": False,
        }

        while True:
            try:
                result = await self._single_snapshot(camera_url, session_id)
                person_detected = result["person_detected"]
                gender = result["gender"]
                age_approx = result["age_approx"]
                age_group = result["age_group"]

                logger.info(
                    "camera_live session=%s detected=%s gender=%s age=%s",
                    session_id,
                    person_detected,
                    gender,
                    age_approx,
                )

                if person_detected:
                    state["consecutive_person_frames"] += 1
                    state["consecutive_empty_frames"] = 0

                    if state["consecutive_person_frames"] >= 2 and not state["greeted"]:
                        state["greeted"] = True
                        logger.info("Triggering proactive greeting for session=%s", session_id)
                        await self._trigger_greeting(
                            session_id,
                            gender=gender,
                            age_approx=age_approx,
                            age_group=age_group,
                        )
                else:
                    state["consecutive_empty_frames"] += 1
                    if state["consecutive_empty_frames"] >= 2:
                        state["consecutive_person_frames"] = 0
                        state["greeted"] = False

                forwarded = await self._forward_snapshot(
                    result,
                    camera_url=camera_url,
                    trace_id=_camera_trace_id(),
                    project_id=project_id,
                    persona_id=persona_id,
                )
                logger.info(
                    "camera_snapshot session_id=%s result_type=%s forwarded=%s",
                    session_id,
                    result.get("type"),
                    forwarded,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("camera_snapshot_err session_id=%s err=%s", session_id, exc)

            await asyncio.sleep(interval)

    async def _trigger_greeting(
        self,
        session_id: str,
        gender: str,
        age_approx: str,
        age_group: str,
    ) -> None:
        """Find the active websocket session and inject a user_speak event to trigger an LLM greeting."""
        try:
            from app.gateway.websocket import _session_manager
            session = _session_manager.get_session(session_id)
            if session and session.brain_live_relay:
                prompt = (
                    f"（系統提示：相機偵測到一位新訪客出現在你面前並停留了幾秒。對方是一位大約 {age_approx} 的{gender}（{age_group}）。"
                    "請親切地主動向他打招呼，開啟話題，詢問需要什麼幫助！）"
                )
                await session.brain_live_relay.send_event({
                    "event": "user_speak",
                    "text": prompt,
                    "timestamp": int(time.time() * 1000)
                })
                logger.info("Successfully sent greeting trigger to session=%s", session_id)
            else:
                logger.warning("Cannot trigger greeting: session or brain_live_relay not found for session_id=%s", session_id)
        except Exception as exc:
            logger.error("Failed to trigger greeting for session_id=%s: %s", session_id, exc)

    async def _single_snapshot(self, camera_url: str, session_id: str) -> dict[str, Any]:
        """Fetch a single snapshot and describe it via Vision LLM."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(camera_url)
            resp.raise_for_status()
            image_bytes = resp.content

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        content_type = resp.headers.get("content-type", "image/jpeg")

        description_raw = await self._describe_image(b64, content_type)
        analysis = _parse_vlm_analysis(description_raw)

        return {
            "type": "camera_snapshot",
            "session_id": session_id,
            "mime_type": content_type,
            **analysis,
        }

    async def _forward_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        camera_url: str,
        trace_id: str,
        project_id: str,
        persona_id: str,
    ) -> bool:
        description = str(snapshot.get("description", "")).strip()
        if not description or "Vision LLM 未設定" in description:
            return False

        return await forward_to_brain(
            trace_id=trace_id,
            session_id=str(snapshot.get("session_id") or ""),
            enriched_context=[
                {
                    "type": "camera_snapshot",
                    "content": description,
                    "source": self.id,
                    "camera_url": camera_url,
                }
            ],
            media_refs=[{"camera_url": camera_url, "mime_type": str(snapshot.get("mime_type") or "image/jpeg")}],
            project_id=project_id,
            persona_id=persona_id,
        )

    async def _describe_image(self, b64_data: str, mime_type: str) -> str:
        """Call Vision LLM to describe the snapshot."""
        from openai import AsyncOpenAI

        cfg = get_tts_config()
        if not cfg.vision_llm_api_key:
            return "（Vision LLM 未設定）"

        client_kwargs: dict[str, Any] = {"api_key": cfg.vision_llm_api_key}
        if cfg.vision_llm_base_url:
            client_kwargs["base_url"] = cfg.vision_llm_base_url

        prompt = (
            "你是一個相機監控分析助手。請詳細分析這張相機快照，判斷畫面中是否有人（包含近處、遠處或剛進入畫面的人）。\n"
            "請嚴格以 JSON 格式回答。回答時「絕對不能」包含任何 markdown 標記（如 ```json 或 ```）或額外的說明文字，只輸出合法的 JSON 字串。\n\n"
            "JSON 格式規範如下：\n"
            "{\n"
            '  "person_detected": true/false (只要畫面中有人就填 true，否則填 false),\n'
            '  "gender": "男性" / "女性" / "不確定" (若有多人，描述最顯眼或最前面的那位),\n'
            '  "age_approx": "大約的年齡，例如 25 歲 / 8 歲 / 65 歲，無法確定填不確定",\n'
            '  "age_group": "兒童" / "青少年" / "青年" / "中年" / "老年" / "不確定",\n'
            '  "description": "簡短的場景與人物描述"\n'
            "}"
        )

        client = AsyncOpenAI(**client_kwargs)
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


def _parse_vlm_analysis(description_raw: str) -> dict[str, Any]:
    """Parse the VLM's JSON reply into structured detection fields.

    The prompt asks for a strict JSON object, but VLMs still wrap it in ```
    fences or emit prose on a bad turn. On any parse failure every field
    degrades to its default ("no person / 不確定"), keeping the raw text as the
    description so nothing is lost.
    """
    defaults: dict[str, Any] = {
        "description": description_raw,
        "person_detected": False,
        "gender": _UNKNOWN,
        "age_approx": _UNKNOWN,
        "age_group": _UNKNOWN,
    }

    json_text = description_raw.strip()
    if json_text.startswith("```"):
        json_text = json_text.split("\n", 1)[-1]
        if json_text.rstrip().endswith("```"):
            json_text = json_text.rstrip()[:-3]

    try:
        analysis = json.loads(json_text)
    except json.JSONDecodeError:
        return defaults
    if not isinstance(analysis, dict):
        return defaults
    return {key: analysis.get(key, default) for key, default in defaults.items()}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _camera_trace_id() -> str:
    return f"camera-{uuid.uuid4().hex}"
