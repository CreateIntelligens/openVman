from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
GENERATED_PYTHON_ROOT = Path(__file__).resolve().parents[3] / "contracts" / "generated" / "python"
if str(GENERATED_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(GENERATED_PYTHON_ROOT))
PROTOCOL_EVENTS_MODULE = "protocol.protocol_events"
GENERATED_PROTOCOL_MODULE = "openvman_contracts.protocol_contracts"


def _import(module_name: str):
    return importlib.import_module(module_name)


def _protocol_events():
    return _import(PROTOCOL_EVENTS_MODULE)


def _generated_protocol_contracts():
    return _import(GENERATED_PROTOCOL_MODULE)


def test_generated_python_contracts_module_is_available():
    generated_contracts = _generated_protocol_contracts()

    assert generated_contracts.DEFAULT_PROTOCOL_VERSION == "1.0.0"


def test_load_protocol_contract_exposes_versioned_machine_readable_schemas():
    protocol_events = _protocol_events()

    contract = protocol_events.load_protocol_contract()

    assert contract["version"] == "1.0.0"
    assert contract["events"]["client_init"]["schema"]["properties"]["event"]["const"] == "client_init"
    assert contract["events"]["server_error"]["schema"]["properties"]["error_code"]["enum"] == [
        "TTS_TIMEOUT",
        "GATEWAY_TIMEOUT",
        "UPLOAD_FAILED",
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
    assert type(event).__module__ == GENERATED_PROTOCOL_MODULE


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


@pytest.mark.parametrize("error_code", ["GATEWAY_TIMEOUT", "UPLOAD_FAILED"])
def test_validate_server_event_accepts_gateway_related_error_codes(error_code):
    protocol_events = _protocol_events()

    event = protocol_events.validate_server_event(
        {
            "event": "server_error",
            "error_code": error_code,
            "message": "gateway failure",
            "timestamp": 1710123480,
        }
    )

    assert event.error_code == error_code


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


# --- handshake tests ---


def _client_init_payload(**overrides):
    return {
        "event": "client_init",
        "client_id": "device_handshake",
        "protocol_version": "1.0.0",
        "auth_token": "token-abc",
        "timestamp": 1710200000,
        **overrides,
    }


def _server_init_ack_payload(**overrides):
    return {
        "event": "server_init_ack",
        "session_id": "sess_001",
        "server_version": "1.0.0",
        "status": "ok",
        "timestamp": 1710200000,
        **overrides,
    }


@pytest.mark.parametrize(
    ("client_version", "server_version", "expected"),
    [
        ("1.0.0", "1.2.3", True),
        ("1.9.0", "1.0.0", True),
        ("2.0.0", "2.5.1", True),
        ("1.0.0", "2.0.0", False),
        ("2.0.0", "1.0.0", False),
        ("0.9.0", "1.0.0", False),
    ],
)
def test_check_version_compatible_uses_major_version(client_version, server_version, expected):
    protocol_events = _protocol_events()

    assert protocol_events.check_version_compatible(client_version, server_version) is expected


def test_perform_handshake_returns_ok_when_versions_compatible():
    protocol_events = _protocol_events()

    ack = protocol_events.perform_handshake(_client_init_payload())

    assert ack["event"] == "server_init_ack"
    assert ack["status"] == "ok"
    assert ack["server_version"] == "1.0.0"
    assert len(ack["session_id"]) > 0
    assert ack["timestamp"] >= 0


def test_perform_handshake_returns_version_mismatch_when_incompatible():
    protocol_events = _protocol_events()

    ack = protocol_events.perform_handshake(
        _client_init_payload(
            client_id="device_old",
            protocol_version="2.0.0",
            auth_token="token-xyz",
        )
    )

    assert ack["event"] == "server_init_ack"
    assert ack["status"] == "version_mismatch"
    assert "message" in ack
    assert "2.0.0" in ack["message"]
    assert "1.0.0" in ack["message"]


def test_perform_handshake_rejects_invalid_client_payload():
    protocol_events = _protocol_events()
    payload = _client_init_payload(client_id="device_bad")
    payload.pop("auth_token")

    with pytest.raises(protocol_events.ProtocolValidationError):
        protocol_events.perform_handshake(payload)


def test_perform_handshake_rejects_non_client_init_event():
    protocol_events = _protocol_events()

    with pytest.raises(protocol_events.ProtocolValidationError) as exc_info:
        protocol_events.perform_handshake(
            {
                "event": "client_interrupt",
                "timestamp": 1710200000,
            }
        )

    assert "client_init" in str(exc_info.value)
    assert "client_interrupt" in str(exc_info.value)


def test_validate_server_event_accepts_valid_server_init_ack():
    protocol_events = _protocol_events()

    event = protocol_events.validate_server_event(_server_init_ack_payload())

    assert event.event == "server_init_ack"
    assert event.session_id == "sess_001"
    assert event.status == "ok"
    assert event.message is None


def test_validate_server_event_accepts_server_init_ack_with_message():
    protocol_events = _protocol_events()

    event = protocol_events.validate_server_event(
        _server_init_ack_payload(
            session_id="sess_002",
            status="version_mismatch",
            message="Client 2.0.0 incompatible with server 1.0.0",
        )
    )

    assert event.status == "version_mismatch"
    assert event.message == "Client 2.0.0 incompatible with server 1.0.0"


def test_validate_server_event_rejects_server_init_ack_with_invalid_status():
    protocol_events = _protocol_events()

    with pytest.raises(protocol_events.ProtocolValidationError) as exc_info:
        protocol_events.validate_server_event(
            _server_init_ack_payload(
                session_id="sess_003",
                status="unknown_status",
            )
        )

    assert "status" in str(exc_info.value)
