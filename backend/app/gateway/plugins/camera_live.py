"""CameraLive plugin — periodic camera snapshot + Vision LLM."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx

from app.config import get_tts_config

logger = logging.getLogger("gateway.plugin.camera_live")


class CameraLivePlugin:
    """Captures periodic snapshots from a camera URL and describes them via Vision LLM."""

    id: str = "camera_live"

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}

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

        if action == "stop":
            await self.cleanup(session_id)
            return {"status": "stopped", "session_id": session_id}

        if action == "snapshot":
            return await self._single_snapshot(camera_url, session_id)

        # action == "start"
        if session_id in self._tasks:
            return {"status": "already_running", "session_id": session_id}

        task = asyncio.create_task(self._snapshot_loop(camera_url, session_id))
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

    async def _snapshot_loop(self, camera_url: str, session_id: str) -> None:
        cfg = get_tts_config()
        interval = cfg.camera_snapshot_interval_sec

        while True:
            try:
                result = await self._single_snapshot(camera_url, session_id)
                logger.info("camera_snapshot session_id=%s result_type=%s", session_id, result.get("type"))
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

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        content_type = resp.headers.get("content-type", "image/jpeg")

        description = await self._describe_image(b64, content_type)
        return {
            "type": "camera_snapshot",
            "session_id": session_id,
            "description": description,
        }

    async def _describe_image(self, b64_data: str, mime_type: str) -> str:
        """Call Vision LLM to describe the snapshot."""
        from openai import AsyncOpenAI

        cfg = get_tts_config()
        if not cfg.vision_llm_api_key:
            return "（Vision LLM 未設定）"

        client_kwargs: dict[str, Any] = {"api_key": cfg.vision_llm_api_key}
        if cfg.vision_llm_base_url:
            client_kwargs["base_url"] = cfg.vision_llm_base_url

        client = AsyncOpenAI(**client_kwargs)
        response = await client.chat.completions.create(
            model=cfg.vision_llm_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "請用繁體中文簡短描述這張相機快照的內容。"},
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
