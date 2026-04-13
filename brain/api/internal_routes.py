"""Internal-only routes used by other backend services."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("brain.internal_routes")

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from protocol.schemas import InternalEnrichRequest

router = APIRouter(tags=["Internal"])


def get_or_create_session(
    session_id: str | None = None,
    persona_id: str = "default",
    project_id: str = "default",
):
    from memory.memory import get_or_create_session as _get_or_create_session

    return _get_or_create_session(session_id, persona_id, project_id=project_id)


def append_session_message(
    session_id: str,
    persona_id: str,
    role: str,
    content: str,
    project_id: str = "default",
):
    from memory.memory import append_session_message as _append_session_message

    return _append_session_message(session_id, persona_id, role, content, project_id=project_id)


def log_event(name: str, **kwargs: Any) -> None:
    from safety.observability import log_event as _log_event

    _log_event(name, **kwargs)


def _get_dreaming_scheduler():
    from memory.dreaming import scheduler

    return scheduler


def _build_live_session(
    relay_session_id: str,
    *,
    client_id: str,
    persona_id: str,
    project_id: str,
    session_id: str = "",
    event_sink,
):
    from live.gemini_live import GeminiLiveSession

    return GeminiLiveSession(
        relay_session_id=relay_session_id,
        client_id=client_id,
        persona_id=persona_id,
        project_id=project_id,
        system_instruction=_build_live_system_instruction(persona_id, project_id, session_id=session_id),
        event_sink=event_sink,
    )


def _build_live_system_instruction(persona_id: str, project_id: str, session_id: str = "") -> str:
    from knowledge.workspace import load_core_workspace_context

    blocks: list[str] = []

    try:
        workspace = load_core_workspace_context(persona_id, project_id=project_id)
        identity = workspace.get("identity", "").strip()
        soul = workspace.get("soul", "").strip()
        if identity:
            blocks.append(identity)
        if soul:
            blocks.append(soul)
    except Exception:
        logger.warning("Failed to load workspace context for live system instruction", exc_info=True)

    history_block = _build_history_context(session_id, persona_id, project_id)
    if history_block:
        blocks.append(history_block)

    memory_block = _build_memory_context(persona_id, project_id)
    if memory_block:
        blocks.append(memory_block)

    if not blocks:
        return ""
    return (
        "你是 openVman Brain 的對話核心。以下是你的角色設定和上下文，請在即時語音對話中遵守。\n\n"
        + "\n\n".join(blocks)
    )


def _build_history_context(session_id: str, persona_id: str, project_id: str) -> str:
    if not session_id:
        return ""
    from memory.memory import list_session_messages

    try:
        messages = list_session_messages(session_id, persona_id=persona_id, project_id=project_id)
    except Exception:
        return ""
    if not messages:
        return ""

    recent = messages[-20:]
    lines = [f"{'使用者' if m['role'] == 'user' else '助手'}: {m['content']}" for m in recent]
    return "以下是之前的對話紀錄，請基於此上下文繼續對話：\n" + "\n".join(lines)


def _build_memory_context(persona_id: str, project_id: str) -> str:
    from memory.retrieval import search_records
    from memory.embedder import encode_query_with_fallback

    try:
        embedding_route = encode_query_with_fallback(
            "使用者偏好與重要記憶",
            project_id=project_id,
            table_names=("memories",),
        )
        results = search_records(
            "memories",
            embedding_route.vector,
            top_k=5,
            query_text="使用者偏好與重要記憶",
            query_type="vector",
            persona_id=persona_id,
            project_id=project_id,
            embedding_version=embedding_route.version,
        )
    except Exception:
        return ""

    if not results:
        return ""

    lines = [str(r.get("text", "")).strip() for r in results if r.get("text")]
    if not lines:
        return ""
    return "以下是與使用者相關的記憶：\n" + "\n".join(f"- {line}" for line in lines)


def _normalize_enriched_items(payload: InternalEnrichRequest) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in payload.enriched_context:
        if content := str(item.get("content", "")).strip():
            normalized.append({
                "type": str(item.get("type", "context")).strip() or "context",
                "content": content,
                "extras": {k: v for k, v in item.items() if k not in {"type", "content"} and v not in (None, "", [], {})},
            })
    return normalized


def _format_enriched_message(item: dict[str, Any], media_refs: list[dict[str, Any]]) -> str:
    lines = [f"[enriched_context:{item['type']}]", item["content"]]
    if item["extras"]:
        lines.append(f"extras: {json.dumps(item['extras'], ensure_ascii=False, sort_keys=True)}")
    if media_paths := [str(r.get("path", "")).strip() for r in media_refs if str(r.get("path", "")).strip()]:
        lines.append(f"media_refs: {', '.join(media_paths)}")
    return "\n".join(lines)


@router.post(
    "/internal/enrich",
    summary="內部對話豐富化",
    description="接收來自其他微服務的外部內容並作為系統訊息存入指定 Session 中。",
)
async def internal_enrich(payload: InternalEnrichRequest):
    items = _normalize_enriched_items(payload)
    if not items:
        raise HTTPException(status_code=400, detail="enriched_context 不可為空")

    session = get_or_create_session(payload.session_id, payload.persona_id, project_id=payload.project_id)
    for item in items:
        append_session_message(
            session.session_id,
            payload.persona_id,
            "system",
            _format_enriched_message(item, payload.media_refs),
            project_id=payload.project_id,
        )

    log_event("internal_enrich", trace_id=payload.trace_id, session_id=session.session_id, stored_count=len(items))
    return {"status": "ok", "trace_id": payload.trace_id, "session_id": session.session_id, "stored_count": len(items)}


@router.websocket("/brain/internal/live/{relay_session_id}")
async def internal_live_bridge(websocket: WebSocket, relay_session_id: str):
    await websocket.accept()
    state: dict[str, Any] = {
        "live_session": None,
        "args": {"client_id": relay_session_id, "persona_id": "default", "project_id": "default"},
        "session_id": relay_session_id,
        "assistant_text_buf": [],
        "client_disconnected": False,
    }

    async def _persisting_event_sink(event: dict) -> None:
        if state["client_disconnected"]:
            return
        evt = event.get("event")
        if evt == "server_stream_chunk":
            text = str(event.get("text") or "").strip()
            if text:
                state["assistant_text_buf"].append(text)
            if event.get("is_final"):
                _flush_assistant_turn(state)
        try:
            await websocket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            state["client_disconnected"] = True

    async def _handle_event(event: str, payload: dict) -> None:
        if event == "relay_init":
            state["args"].update({
                "client_id": str(payload.get("client_id", relay_session_id)) or relay_session_id,
                "persona_id": str(payload.get("persona_id", "default")) or "default",
                "project_id": str(payload.get("project_id", "default")) or "default",
            })
            chat_session_id = str(payload.get("chat_session_id", "")).strip()
            if chat_session_id:
                state["session_id"] = chat_session_id
            _ensure_live_session(state, relay_session_id, _persisting_event_sink)
            return

        _ensure_live_session(state, relay_session_id, _persisting_event_sink)

        if event == "user_speak":
            if text := str(payload.get("text", "")).strip():
                _save_user_message(state, text)
                await state["live_session"].send_text_turn(text)
        elif event == "client_interrupt":
            await state["live_session"].request_stop()
        elif event == "client_audio_chunk":
            audio_b64 = str(payload.get("audio_base64", "")).strip()
            mime_type = str(payload.get("mime_type", "audio/pcm;rate=16000")).strip()
            if audio_b64:
                await state["live_session"].send_realtime_input(audio_b64, mime_type)
        elif event == "client_audio_end":
            await state["live_session"].send_turn_complete()

    try:
        while True:
            payload = await websocket.receive_json()
            await _handle_event(str(payload.get("event", "")).strip(), payload)
    except WebSocketDisconnect:
        pass
    finally:
        _flush_assistant_turn(state)
        if state["live_session"]:
            await state["live_session"].close()


def _ensure_session(state: dict[str, Any]) -> None:
    args = state["args"]
    session = get_or_create_session(state["session_id"], args["persona_id"], project_id=args["project_id"])
    state["session_id"] = session.session_id


def _ensure_live_session(state: dict[str, Any], relay_session_id: str, event_sink) -> None:
    if state["live_session"]:
        return
    _ensure_session(state)
    state["live_session"] = _build_live_session(
        relay_session_id,
        event_sink=event_sink,
        session_id=state["session_id"],
        **state["args"],
    )


def _save_user_message(state: dict[str, Any], text: str) -> None:
    _flush_assistant_turn(state)
    args = state["args"]
    append_session_message(state["session_id"], args["persona_id"], "user", text, project_id=args["project_id"])


def _flush_assistant_turn(state: dict[str, Any]) -> None:
    buf = state["assistant_text_buf"]
    if not buf:
        return
    full_text = "".join(buf).strip()
    state["assistant_text_buf"] = []
    if not full_text:
        return
    args = state["args"]
    append_session_message(state["session_id"], args["persona_id"], "assistant", full_text, project_id=args["project_id"])


# ---------------------------------------------------------------------------
# Dreaming
# ---------------------------------------------------------------------------

@router.get(
    "/brain/dreaming/status",
    tags=["Dreaming"],
    summary="Dreaming 狀態",
    description="取得背景記憶整合系統的啟用狀態、上次執行結果與配置。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def dreaming_status(project_id: str = "default"):
    scheduler = _get_dreaming_scheduler()
    return scheduler.get_dreaming_status(project_id)


@router.post(
    "/brain/dreaming/run",
    tags=["Dreaming"],
    summary="手動觸發 Dreaming",
    description="手動執行一次完整的 Light → Deep → REM 記憶整合週期。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID\n- `force` (Query, bool, 預設 false): 強制執行（忽略今日已執行檢查）",
)
async def dreaming_run(project_id: str = "default", force: bool = False):
    import asyncio

    scheduler = _get_dreaming_scheduler()
    result = await asyncio.to_thread(
        scheduler.run_dreaming_cycle,
        project_id,
        force=force,
    )
    return result


@router.get(
    "/brain/dreaming/candidates",
    tags=["Dreaming"],
    summary="預覽候選記憶",
    description="預覽 Light Phase 產生的候選記憶列表（不會 promote）。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def dreaming_candidates(project_id: str = "default"):
    scheduler = _get_dreaming_scheduler()
    candidates = scheduler.get_candidates_preview(project_id)
    return {"candidates": candidates, "count": len(candidates)}


@router.get(
    "/brain/dreaming/report",
    tags=["Dreaming"],
    summary="最近 Deep Phase 報告",
    description="取得最近一次 Deep Phase 的執行報告。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def dreaming_report(project_id: str = "default"):
    scheduler = _get_dreaming_scheduler()
    content = scheduler.get_latest_report(project_id)
    if not content:
        return {"report": None, "message": "尚無報告"}
    return {"report": content}
