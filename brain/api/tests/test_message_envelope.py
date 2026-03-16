"""Tests for protocol.message_envelope — normalize, enrich, BrainMessage."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

MESSAGE_ENVELOPE_MODULE = "protocol.message_envelope"


def _module():
    return importlib.import_module(MESSAGE_ENVELOPE_MODULE)


def _fake_request(
    *,
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
    state_attrs: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a minimal FastAPI Request mock."""
    request = MagicMock()
    request.headers = headers or {}
    request.client = SimpleNamespace(host=client_host)
    state = SimpleNamespace(**(state_attrs or {}))
    request.state = state
    return request


# --- build_message_envelope tests ---


def test_build_envelope_from_flat_body():
    mod = _module()
    body = {
        "message": "你好",
        "session_id": "sess_01",
        "persona_id": "doctor",
        "locale": "en-US",
        "channel": "kiosk",
    }
    envelope = mod.build_message_envelope(_fake_request(), body)

    assert envelope.content == "你好"
    assert envelope.context.session_id == "sess_01"
    assert envelope.context.persona_id == "doctor"
    assert envelope.context.locale == "en-US"
    assert envelope.context.channel == "kiosk"
    assert envelope.context.message_type == "user"


def test_build_envelope_from_structured_message():
    mod = _module()
    body = {
        "message": {
            "content": "結構化內容",
            "session_id": "sess_nested",
            "locale": "ja-JP",
        },
    }
    envelope = mod.build_message_envelope(_fake_request(), body)

    assert envelope.content == "結構化內容"
    assert envelope.context.session_id == "sess_nested"
    assert envelope.context.locale == "ja-JP"


def test_build_envelope_enriches_trace_id_from_header():
    mod = _module()
    request = _fake_request(headers={"x-trace-id": "trace-from-header"})
    envelope = mod.build_message_envelope(request, {"message": "hi"})

    assert envelope.context.trace_id == "trace-from-header"


def test_build_envelope_auto_generates_trace_id():
    mod = _module()
    envelope = mod.build_message_envelope(_fake_request(), {"message": "hi"})

    assert len(envelope.context.trace_id) > 0


def test_build_envelope_locale_defaults_to_zh_tw():
    mod = _module()
    envelope = mod.build_message_envelope(_fake_request(), {"message": "hi"})

    assert envelope.context.locale == "zh-TW"


def test_build_envelope_persona_defaults_to_default():
    mod = _module()
    envelope = mod.build_message_envelope(_fake_request(), {"message": "hi"})

    assert envelope.context.persona_id == "default"


def test_build_envelope_merges_metadata():
    mod = _module()
    body = {
        "message": {"content": "x", "metadata": {"inner": "val"}},
        "metadata": {"outer": "val2"},
    }
    envelope = mod.build_message_envelope(_fake_request(), body)

    assert envelope.context.metadata["outer"] == "val2"
    assert envelope.context.metadata["inner"] == "val"


def test_serialize_context_roundtrip():
    mod = _module()
    envelope = mod.build_message_envelope(
        _fake_request(),
        {"message": "test", "persona_id": "nurse", "locale": "zh-TW"},
    )
    serialized = mod.serialize_context(envelope.context)

    assert serialized["persona_id"] == "nurse"
    assert serialized["locale"] == "zh-TW"
    assert serialized["trace_id"] == envelope.context.trace_id
    assert serialized["message_type"] == "user"
    assert isinstance(serialized, dict)


# --- BrainMessage tests ---


def test_normalize_to_brain_message_preserves_all_context():
    mod = _module()
    envelope = mod.build_message_envelope(
        _fake_request(),
        {
            "message": "保留測試",
            "session_id": "sess_preserve",
            "persona_id": "guide",
            "locale": "zh-TW",
            "channel": "api",
            "metadata": {"key": "value"},
        },
    )
    brain_msg = mod.normalize_to_brain_message(envelope)

    assert brain_msg.role == "user"
    assert brain_msg.content == "保留測試"
    assert brain_msg.trace_id == envelope.context.trace_id
    assert brain_msg.session_id == "sess_preserve"
    assert brain_msg.persona_id == "guide"
    assert brain_msg.locale == "zh-TW"
    assert brain_msg.channel == "api"
    assert brain_msg.metadata["key"] == "value"


def test_normalize_to_brain_message_maps_message_type_to_role():
    mod = _module()
    envelope = mod.build_message_envelope(
        _fake_request(),
        {"message": "tool result", "message_type": "tool"},
    )
    brain_msg = mod.normalize_to_brain_message(envelope)

    assert brain_msg.role == "tool"


def test_create_brain_message_for_system_role():
    mod = _module()
    context = mod.RequestContext(
        trace_id="trace_sys",
        session_id="sess_sys",
        message_type="user",
        channel="web",
        locale="zh-TW",
        persona_id="default",
        project_id="default",
        client_ip="127.0.0.1",
        metadata={},
    )
    brain_msg = mod.create_brain_message("system", "你是一位醫生", context=context)

    assert brain_msg.role == "system"
    assert brain_msg.content == "你是一位醫生"
    assert brain_msg.trace_id == "trace_sys"
    assert brain_msg.persona_id == "default"


def test_create_brain_message_for_assistant_role():
    mod = _module()
    context = mod.RequestContext(
        trace_id="trace_ast",
        session_id="sess_ast",
        message_type="user",
        channel="web",
        locale="zh-TW",
        persona_id="doctor",
        project_id="default",
        client_ip="127.0.0.1",
        metadata={"source": "llm"},
    )
    brain_msg = mod.create_brain_message("assistant", "我可以幫你", context=context)

    assert brain_msg.role == "assistant"
    assert brain_msg.content == "我可以幫你"
    assert brain_msg.persona_id == "doctor"


def test_brain_message_metadata_is_defensive_copy():
    mod = _module()
    original_metadata = {"key": "original"}
    context = mod.RequestContext(
        trace_id="trace_dc",
        session_id=None,
        message_type="user",
        channel="web",
        locale="zh-TW",
        persona_id="default",
        project_id="default",
        client_ip="127.0.0.1",
        metadata=original_metadata,
    )
    brain_msg = mod.create_brain_message("user", "test", context=context)

    brain_msg.metadata["key"] = "modified"
    assert original_metadata["key"] == "original"
