"""Filesystem checks for vendor requests already authorized by Backend."""

from pathlib import Path
from typing import Annotated

from fastapi import Header, HTTPException

from core.sse_events import build_protocol_error
from knowledge.workspace import get_workspace_root

VENDOR_HEADER = "X-OpenVMan-Vendor"
VENDOR_CHAT_ERROR = "對話暫時無法完成，請稍後再試。"
VendorRequest = Annotated[bool, Header(alias=VENDOR_HEADER, include_in_schema=False)]


def vendor_workspace_path(project_id: str, relative: str, area: str) -> Path:
    """Require a regular entry at its own path, without filesystem aliases."""
    # Document and directory operations trim input before resolving it.
    if relative != relative.strip():
        raise HTTPException(status_code=403, detail="沒有權限使用這個功能。")
    path = Path(relative)
    root = get_workspace_root(project_id).resolve()
    target = root / path
    parts = path.parts
    is_soul = area == "soul"
    is_qa_image = area == "qa_image"
    if is_soul:
        permitted = parts == ("SOUL.md",) or (
            len(parts) == 3 and parts[0] == "personas" and parts[2] == "SOUL.md"
        )
    elif is_qa_image:
        permitted = len(parts) == 3 and parts[:2] == ("knowledge", ".qa_images")
    else:
        permitted = len(parts) >= 2 and parts[0] == area and not any(
            part.startswith(".") or part in {"graphify-out", "_catalog.yaml"}
            for part in parts[1:]
        )
    if (
        path.is_absolute()
        or any(part == ".." for part in parts)
        or not permitted
    ):
        raise HTTPException(status_code=403, detail="沒有權限使用這個功能。")
    try:
        if target.resolve() == target and (
            not target.exists() or target.is_dir() or (
                target.is_file() and target.stat().st_nlink == 1
            )
        ):
            return target
    except (OSError, RuntimeError, ValueError):
        pass
    raise HTTPException(status_code=403, detail="沒有權限使用這個功能。")


def visible_workspace_path(project_id: str, relative: str, area: str) -> bool:
    try:
        vendor_workspace_path(project_id, relative, area)
    except HTTPException:
        return False
    return True


def _pick(data: dict, keys: str) -> dict:
    return {key: data[key] for key in keys.split() if key in data}


def vendor_chat_history(messages: list[dict]) -> list[dict]:
    return [
        _pick(message, "role content created_at image_id image_kind url")
        for message in messages
        if message.get("role") in {"user", "assistant"}
    ]


def vendor_chat_reply(data: dict) -> dict:
    result = _pick(
        data, "status reply session_id persona_id answer_source knowledge_searched "
        "no_answer pii_pending image_id image_kind url tts_text "
        "turn_id turn_revision requires_accept",
    )
    if "history" in data:
        result["history"] = vendor_chat_history(data["history"])
    return result


def vendor_live_event(data: dict) -> dict | None:
    event = data.get("event")
    if event == "server_error":
        return build_protocol_error("INTERNAL_ERROR", VENDOR_CHAT_ERROR)
    fields = {
        "server_stream_chunk": "chunk_id text audio_base64 is_final",
        "server_stop_audio": "timestamp reason",
        "user_transcription": "timestamp text",
    }.get(event)
    if fields is None:
        return None
    return _pick(data, f"event session_id {fields}")


def vendor_session_summary(session: dict) -> dict:
    return _pick(
        session, "session_id persona_id created_at updated_at language "
        "message_count last_message_preview",
    )
