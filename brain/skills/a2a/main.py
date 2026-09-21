"""Skill: A2A Network — Invokes Backend internal facade without touching Hub credentials."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlencode
import urllib.error
import urllib.request

logger = logging.getLogger("brain.skills.a2a")

_MAX_ID_LENGTH = 256
_MAX_MESSAGE_BYTES = 1024 * 1024


def _validation_error(
    value: Any, field: str, *, required: bool = True,
) -> str | None:
    if value is None:
        value = ""
    if not isinstance(value, str):
        return f"{field} must be a string"
    text = value.strip()
    if not text:
        return f"{field} is required" if required else None
    if field.endswith("_id"):
        length, limit = len(text), _MAX_ID_LENGTH
    else:
        length, limit = len(text.encode("utf-8")), _MAX_MESSAGE_BYTES
    if length > limit:
        return f"{field} is too long"
    return None


def _request_json(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not token:
        return {"error": "Backend internal token is not configured"}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-Internal-Token": token},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            decoded = json.loads(resp.read(2 * _MAX_MESSAGE_BYTES).decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {"error": "Invalid Backend response"}
    except urllib.error.HTTPError as exc:
        return {"error": f"Internal facade returned HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("A2A internal facade request failed type=%s", type(exc).__name__)
        return {"error": "A2A internal facade unavailable"}


def _get_backend_facade_config() -> tuple[str, str]:
    """Get internal Backend base URL and gateway internal token."""
    # Within Docker network, Backend is at http://backend:8200; locally http://127.0.0.1:8200
    backend_url = os.environ.get("BACKEND_INTERNAL_URL") or os.environ.get("GATEWAY_FORWARD_URL") or "http://backend:8200"
    backend_url = backend_url.rstrip("/")
    token = os.environ.get("GATEWAY_INTERNAL_TOKEN", "")
    return backend_url, token


def a2a_list_peers(args: dict[str, Any]) -> dict[str, Any]:
    """List online peer agents via Backend internal facade."""
    backend_url, token = _get_backend_facade_config()
    state = str(args.get("state") or "").strip().lower()
    if state not in {"", "all", "online", "offline"}:
        return {"error": "state must be one of: all, online, offline"}
    url = f"{backend_url}/api/v1/internal/a2a/peers"
    if state and state != "all":
        url += "?" + urlencode({"state": state})
    data = _request_json("GET", url, token)
    if "error" in data:
        return data
    peers = data.get("peers", [])
    return {"peers": peers, "total": len(peers)}


def a2a_send_task(args: dict[str, Any]) -> dict[str, Any]:
    """Send a task message to a target peer agent via Backend internal facade."""
    target_agent_id = args.get("target_agent_id")
    message = args.get("message")
    context_id = args.get("context_id")
    hop_count = args.get("hop_count", 1)

    if error := _validation_error(target_agent_id, "target_agent_id"):
        return {"error": error}
    if error := _validation_error(message, "message"):
        return {"error": error}
    if error := _validation_error(context_id, "context_id", required=False):
        return {"error": error}
    if (
        isinstance(hop_count, bool)
        or not isinstance(hop_count, int)
        or not 0 <= hop_count <= 10
    ):
        return {"error": "hop_count must be an integer between 0 and 10"}

    backend_url, token = _get_backend_facade_config()
    url = f"{backend_url}/api/v1/internal/a2a/tasks"
    payload = {
        "target_agent_id": target_agent_id.strip(),
        "message": message.strip(),
        "context_id": (context_id or "").strip() or None,
        "hop_count": hop_count,
    }
    return _request_json("POST", url, token, payload)


def a2a_broadcast_group(args: dict[str, Any]) -> dict[str, Any]:
    """Broadcast a message to an active group via Backend internal facade."""
    group_id = args.get("group_id")
    message = args.get("message")

    if error := _validation_error(group_id, "group_id"):
        return {"error": error}
    if error := _validation_error(message, "message"):
        return {"error": error}

    backend_url, token = _get_backend_facade_config()
    url = f"{backend_url}/api/v1/internal/a2a/groups/messages"
    return _request_json(
        "POST",
        url,
        token,
        {"group_id": group_id.strip(), "message": message.strip()},
    )
