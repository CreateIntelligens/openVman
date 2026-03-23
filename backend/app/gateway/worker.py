"""Arq worker functions for media processing."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from app.gateway.plugins import IPlugin

from app.gateway.dispatcher import dispatch
from app.gateway.forward import forward_to_brain
from app.gateway.job_status import set_job_status
from app.gateway.plugins.api_tool import ApiToolPlugin
from app.gateway.plugins.camera_live import CameraLivePlugin
from app.gateway.plugins.web_crawler import WebCrawlerPlugin
from app.gateway.queue import push_to_dlq

logger = logging.getLogger("gateway.worker")

# --- Plugin singletons (shared across jobs) ---
_camera_plugin: CameraLivePlugin | None = None
_api_tool_plugin: ApiToolPlugin | None = None
_web_crawler_plugin: WebCrawlerPlugin | None = None

_FAILURE_MESSAGES = {
    "GATEWAY_TIMEOUT": "插件服務回應逾時",
    "BRAIN_UNAVAILABLE": "後端處理服務暫時無法使用",
}


def get_camera_plugin() -> CameraLivePlugin:
    global _camera_plugin
    if _camera_plugin is None:
        _camera_plugin = CameraLivePlugin()
    return _camera_plugin


def get_api_tool_plugin() -> ApiToolPlugin:
    global _api_tool_plugin
    if _api_tool_plugin is None:
        _api_tool_plugin = ApiToolPlugin()
    return _api_tool_plugin


def get_web_crawler_plugin() -> WebCrawlerPlugin:
    global _web_crawler_plugin
    if _web_crawler_plugin is None:
        _web_crawler_plugin = WebCrawlerPlugin()
    return _web_crawler_plugin


async def _run_plugin_job(
    job_name: str,
    plugin_getter: Callable[[], IPlugin],
    data: dict[str, Any],
) -> dict[str, Any]:
    """Execute a plugin job with DLQ error handling.

    Shared logic for all plugin-based worker functions.
    """
    trace_id = data.get("trace_id", "unknown")
    logger.info("%s trace_id=%s", job_name, trace_id)

    try:
        plugin = plugin_getter()
        return await plugin.execute(data)
    except Exception as exc:
        logger.error("%s_failed trace_id=%s err=%s", job_name, trace_id, exc)
        await push_to_dlq({
            "job_name": job_name,
            "trace_id": trace_id,
            "error": str(exc),
            "ts": time.time(),
        })
        raise


async def _set_job_failed(job_id: str, failure: dict[str, Any]) -> None:
    """Mark a job as failed, forwarding all failure fields except 'status'."""
    await set_job_status(
        job_id, "failed", **{k: v for k, v in failure.items() if k != "status"}
    )


async def process_media(ctx: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Process uploaded media through the dispatcher, then forward to brain."""
    file_path = data.get("file_path", "")
    mime_type = data.get("mime_type", "")
    session_id = data.get("session_id", "")
    trace_id = data.get("trace_id", "unknown")
    job_id = data.get("job_id", "") or data.get("__job_id", "")

    logger.info("process_media trace_id=%s mime_type=%s", trace_id, mime_type)

    try:
        if job_id:
            await set_job_status(job_id, "processing")

        result = await dispatch(file_path, mime_type, trace_id)

        if result.get("type") == "processing_error":
            failure = {
                "status": "failed",
                **result,
                "message": _FAILURE_MESSAGES.get(result.get("error_code", ""), "媒體處理失敗"),
            }
            if job_id:
                await _set_job_failed(job_id, failure)
            return failure

        forward_ok = await forward_to_brain(
            trace_id=trace_id,
            session_id=session_id,
            enriched_context=[result],
            media_refs=[{"path": file_path, "mime_type": mime_type}],
        )

        if not forward_ok:
            failure = {
                "status": "failed",
                **result,
                "error_code": "BRAIN_UNAVAILABLE",
                "error": "brain_unavailable",
                "message": _FAILURE_MESSAGES["BRAIN_UNAVAILABLE"],
            }
            if job_id:
                await _set_job_failed(job_id, failure)
            return failure

        completed = {"status": "completed", **result}
        if job_id:
            await set_job_status(job_id, "completed", **result)

        return completed

    except Exception as exc:
        logger.error("process_media_failed trace_id=%s err=%s", trace_id, exc)
        if job_id:
            await set_job_status(
                job_id,
                "failed",
                error_code="UPLOAD_FAILED",
                error=str(exc),
                message="檔案處理失敗",
            )
        await push_to_dlq({
            "job_name": "process_media",
            "trace_id": trace_id,
            "session_id": session_id,
            "file_path": file_path,
            "mime_type": mime_type,
            "error": str(exc),
            "ts": time.time(),
        })
        raise


async def process_camera(ctx: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Process camera snapshot request via CameraLive plugin."""
    return await _run_plugin_job("process_camera", get_camera_plugin, data)


async def process_api_tool(ctx: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Process API tool request via ApiTool plugin."""
    return await _run_plugin_job("process_api_tool", get_api_tool_plugin, data)


async def process_web_crawler(ctx: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Process web crawler request via WebCrawler plugin."""
    return await _run_plugin_job("process_web_crawler", get_web_crawler_plugin, data)


def reset_plugins() -> None:
    """Reset plugin singletons (used in tests and shutdown)."""
    global _camera_plugin, _api_tool_plugin, _web_crawler_plugin
    _camera_plugin = None
    _api_tool_plugin = None
    _web_crawler_plugin = None


class WorkerSettings:
    """Arq worker settings — used when running arq as a standalone worker."""

    functions = [process_media, process_camera, process_api_tool, process_web_crawler]
    queue_name = "vman:gateway"
    max_jobs = 10
