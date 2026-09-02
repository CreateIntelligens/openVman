"""Public serialization helpers for stored chat history."""

from __future__ import annotations

from typing import Any

from protocol.message_envelope import METADATA_ACTION_REQUESTS


def serialize_history_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose supported message metadata without leaking internal fields."""
    history: list[dict[str, Any]] = []
    for message in messages:
        metadata = message.get("metadata")
        entry = {key: value for key, value in message.items() if key != "metadata"}
        if isinstance(metadata, dict):
            action_requests = metadata.get(METADATA_ACTION_REQUESTS)
            if isinstance(action_requests, list) and action_requests:
                entry[METADATA_ACTION_REQUESTS] = action_requests

            tool_steps = metadata.get("tool_steps")
            if isinstance(tool_steps, list) and tool_steps:
                entry["tool_steps"] = tool_steps

            response_time_s = metadata.get("response_time_s")
            if response_time_s is not None:
                entry["response_time_s"] = response_time_s

            privacy_warning = metadata.get("privacy_warning")
            if isinstance(privacy_warning, dict) and privacy_warning:
                entry["privacy_warning"] = privacy_warning

            citations = metadata.get("citations")
            if isinstance(citations, list) and citations:
                entry["citations"] = citations

            image_id = metadata.get("image_id")
            if isinstance(image_id, str) and image_id:
                entry["image_id"] = image_id

            url = metadata.get("url")
            if isinstance(url, str) and url:
                entry["url"] = url
        history.append(entry)
    return history
