"""Versioned core protocol contract loading and runtime validation."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

DEFAULT_PROTOCOL_VERSION = "1.0.0"
_VERSION_DIRECTORIES = {
    "1.0.0": "v1",
}
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
ProtocolDirection = Literal["client_to_server", "server_to_client"]


class ProtocolValidationError(ValueError):
    """Raised when payloads do not match the declared protocol contract."""

    def __init__(
        self,
        message: str,
        *,
        version: str,
        event: str = "",
        details: list[str] | None = None,
    ) -> None:
        self.version = version
        self.event = event
        self.details = details or []
        super().__init__(message)


class ProtocolBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientInitEvent(ProtocolBaseModel):
    event: Literal["client_init"]
    client_id: str = Field(min_length=1, max_length=128)
    protocol_version: str = Field(pattern=_SEMVER_PATTERN)
    auth_token: str = Field(min_length=1)
    capabilities: dict[str, str] = Field(default_factory=dict)
    timestamp: int = Field(ge=0)


class UserSpeakEvent(ProtocolBaseModel):
    event: Literal["user_speak"]
    text: str = Field(min_length=1)
    timestamp: int = Field(ge=0)


class ClientInterruptEvent(ProtocolBaseModel):
    event: Literal["client_interrupt"]
    timestamp: int = Field(ge=0)


class VisemeFrame(ProtocolBaseModel):
    time: float = Field(ge=0)
    value: Literal["closed", "A", "E", "I", "O", "U"]


class ServerStreamChunkEvent(ProtocolBaseModel):
    event: Literal["server_stream_chunk"]
    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    audio_base64: str = Field(min_length=1)
    visemes: list[VisemeFrame]
    emotion: str | None = Field(default=None, min_length=1)
    is_final: bool


class ServerErrorEvent(ProtocolBaseModel):
    event: Literal["server_error"]
    error_code: Literal[
        "TTS_TIMEOUT",
        "LLM_OVERLOAD",
        "BRAIN_UNAVAILABLE",
        "AUTH_FAILED",
        "SESSION_EXPIRED",
        "INTERNAL_ERROR",
    ]
    message: str = Field(min_length=1)
    retry_after_ms: int | None = Field(default=None, ge=0)
    timestamp: int = Field(ge=0)


ClientEvent = Annotated[
    ClientInitEvent | UserSpeakEvent | ClientInterruptEvent,
    Field(discriminator="event"),
]
ServerEvent = Annotated[
    ServerStreamChunkEvent | ServerErrorEvent,
    Field(discriminator="event"),
]

_CLIENT_EVENT_ADAPTER = TypeAdapter(ClientEvent)
_SERVER_EVENT_ADAPTER = TypeAdapter(ServerEvent)


def load_protocol_contract(version: str = DEFAULT_PROTOCOL_VERSION) -> dict[str, Any]:
    directory = _resolve_version_directory(version)
    manifest_path = _resolve_protocol_root() / directory / "manifest.json"
    manifest = _read_json(manifest_path)
    contract = dict(manifest)
    contract["events"] = {
        event_name: {
            **event_config,
            "schema": _read_json(manifest_path.parent / event_config["schema"]),
        }
        for event_name, event_config in manifest["events"].items()
    }
    return contract


def validate_client_event(
    payload: dict[str, Any],
    version: str = DEFAULT_PROTOCOL_VERSION,
) -> ClientInitEvent | UserSpeakEvent | ClientInterruptEvent:
    return _validate_event_payload(
        payload,
        version=version,
        allowed_direction="client_to_server",
        adapter=_CLIENT_EVENT_ADAPTER,
    )


def validate_server_event(
    payload: dict[str, Any],
    version: str = DEFAULT_PROTOCOL_VERSION,
) -> ServerStreamChunkEvent | ServerErrorEvent:
    return _validate_event_payload(
        payload,
        version=version,
        allowed_direction="server_to_client",
        adapter=_SERVER_EVENT_ADAPTER,
    )


def _validate_event_payload(
    payload: dict[str, Any],
    *,
    version: str,
    allowed_direction: ProtocolDirection,
    adapter: TypeAdapter[Any],
) -> Any:
    contract = load_protocol_contract(version)
    event_name = str(payload.get("event", "")).strip()
    if not event_name:
        raise ProtocolValidationError(
            "Protocol payload is missing `event`",
            version=version,
        )

    event_config = contract["events"].get(event_name)
    if not event_config or event_config["direction"] != allowed_direction:
        raise ProtocolValidationError(
            f"Unsupported {allowed_direction} event `{event_name}` for contract {version}",
            version=version,
            event=event_name,
        )

    try:
        return adapter.validate_python(payload)
    except ValidationError as exc:
        details = _format_validation_errors(exc)
        detail_message = "; ".join(details)
        raise ProtocolValidationError(
            f"Invalid protocol payload for `{event_name}`: {detail_message}",
            version=version,
            event=event_name,
            details=details,
        ) from exc


def _format_validation_errors(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in item.get('loc', [])) or 'payload'}: {item.get('msg', 'Invalid value')}"
        for item in exc.errors()
    ]


def _resolve_version_directory(version: str) -> str:
    directory = _VERSION_DIRECTORIES.get(version)
    if directory:
        return directory
    raise ProtocolValidationError(
        f"Unsupported protocol contract version: {version}",
        version=version,
    )


@lru_cache(maxsize=None)
def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _resolve_protocol_root() -> Path:
    resolved_path = Path(__file__).resolve()
    candidates = [Path("/contracts/schemas")]
    project_root = _resolve_project_root(resolved_path)
    if project_root is not None:
        candidates.append(project_root / "contracts" / "schemas")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ProtocolValidationError(
        "Protocol schema directory not found",
        version=DEFAULT_PROTOCOL_VERSION,
    )


def _resolve_project_root(resolved_path: Path) -> Path | None:
    if len(resolved_path.parents) < 3:
        return None
    return resolved_path.parents[2]
