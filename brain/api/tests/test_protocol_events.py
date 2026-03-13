from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
PROTOCOL_EVENTS_MODULE = "protocol.protocol_events"


def _import(module_name: str):
    return importlib.import_module(module_name)


def _protocol_events():
    return _import(PROTOCOL_EVENTS_MODULE)


def test_load_protocol_contract_exposes_versioned_machine_readable_schemas():
    protocol_events = _protocol_events()

    contract = protocol_events.load_protocol_contract()

    assert contract["version"] == "1.0.0"
    assert contract["events"]["client_init"]["schema"]["properties"]["event"]["const"] == "client_init"
    assert contract["events"]["server_error"]["schema"]["properties"]["error_code"]["enum"] == [
        "TTS_TIMEOUT",
        "LLM_OVERLOAD",
        "BRAIN_UNAVAILABLE",
        "AUTH_FAILED",
        "SESSION_EXPIRED",
        "INTERNAL_ERROR",
    ]


def test_validate_client_event_accepts_valid_client_init_payload():
    protocol_events = _protocol_events()

    event = protocol_events.validate_client_event(
        {
            "event": "client_init",
            "client_id": "device_001",
            "protocol_version": "1.0.0",
            "auth_token": "test-token",
            "capabilities": {
                "asr": "webkitSpeechRecognition",
                "max_audio_format": "wav",
            },
            "timestamp": 1710123456,
        }
    )

    assert event.event == "client_init"
    assert event.client_id == "device_001"
    assert event.protocol_version == "1.0.0"
    assert event.capabilities["asr"] == "webkitSpeechRecognition"


def test_validate_server_event_accepts_valid_stream_chunk_payload():
    protocol_events = _protocol_events()

    event = protocol_events.validate_server_event(
        {
            "event": "server_stream_chunk",
            "chunk_id": "msg_001_chunk_01",
            "text": "這套架構最大的優勢，",
            "audio_base64": "UklGRi0AAABXQVZFZm10",
            "visemes": [
                {"time": 0.0, "value": "closed"},
                {"time": 0.05, "value": "A"},
            ],
            "emotion": "smile",
            "is_final": False,
        }
    )

    assert event.event == "server_stream_chunk"
    assert event.chunk_id == "msg_001_chunk_01"
    assert event.visemes[1].value == "A"


def test_validate_client_event_rejects_missing_required_field():
    protocol_events = _protocol_events()

    with pytest.raises(protocol_events.ProtocolValidationError) as exc_info:
        protocol_events.validate_client_event(
            {
                "event": "client_init",
                "client_id": "device_001",
                "protocol_version": "1.0.0",
                "timestamp": 1710123456,
            }
        )

    assert "auth_token" in str(exc_info.value)


def test_validate_server_event_rejects_unknown_error_code():
    protocol_events = _protocol_events()

    with pytest.raises(protocol_events.ProtocolValidationError) as exc_info:
        protocol_events.validate_server_event(
            {
                "event": "server_error",
                "error_code": "WRONG_CODE",
                "message": "bad",
                "timestamp": 1710123480,
            }
        )

    assert "error_code" in str(exc_info.value)


def test_validate_client_event_rejects_extra_fields_consistently():
    protocol_events = _protocol_events()

    with pytest.raises(protocol_events.ProtocolValidationError) as exc_info:
        protocol_events.validate_client_event(
            {
                "event": "client_interrupt",
                "timestamp": 1710123465,
                "unexpected": True,
            }
        )

    assert "unexpected" in str(exc_info.value)


def test_load_protocol_contract_rejects_unknown_version():
    protocol_events = _protocol_events()

    with pytest.raises(protocol_events.ProtocolValidationError) as exc_info:
        protocol_events.load_protocol_contract("9.9.9")

    assert "Unsupported protocol contract version" in str(exc_info.value)
