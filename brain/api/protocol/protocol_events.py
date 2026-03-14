"""Versioned core protocol contract loading and runtime validation."""

from __future__ import annotations

import json
import sys
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

DEFAULT_PROTOCOL_VERSION = "1.0.0"


def _ensure_generated_contracts_import_path() -> None:
    generated_python_root = _resolve_generated_python_root()
    if str(generated_python_root) not in sys.path:
        sys.path.insert(0, str(generated_python_root))


_VERSION_DIRECTORIES = {
    "1.0.0": "v1",
}


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


def load_protocol_contract(version: str = DEFAULT_PROTOCOL_VERSION) -> dict[str, Any]:
    directory = _resolve_version_directory(version)
    manifest_path = _resolve_protocol_root() / directory / "manifest.json"
    manifest = _read_json(manifest_path)
    return {
        **manifest,
        "events": _load_contract_events(manifest_path, manifest["events"]),
    }


def validate_client_event(
    payload: dict[str, Any],
    version: str = DEFAULT_PROTOCOL_VERSION,
) -> ClientInitEvent | UserSpeakEvent | ClientInterruptEvent:
    return _validate_event_payload(
        payload,
        version=version,
        allowed_direction="client_to_server",
        adapter=CLIENT_EVENT_ADAPTER,
    )


def validate_server_event(
    payload: dict[str, Any],
    version: str = DEFAULT_PROTOCOL_VERSION,
) -> ServerStreamChunkEvent | ServerErrorEvent | ServerInitAckEvent:
    return _validate_event_payload(
        payload,
        version=version,
        allowed_direction="server_to_client",
        adapter=SERVER_EVENT_ADAPTER,
    )


def check_version_compatible(client_version: str, server_version: str) -> bool:
    """Return True if MAJOR versions match (semver §6)."""
    return client_version.split(".")[0] == server_version.split(".")[0]


def perform_handshake(
    client_payload: dict[str, Any],
    version: str = DEFAULT_PROTOCOL_VERSION,
) -> dict[str, Any]:
    """Validate a client_init payload and return a server_init_ack dict."""
    client_event = validate_client_event(client_payload, version)
    client_version = client_event.protocol_version

    if check_version_compatible(client_version, version):
        return _build_server_init_ack(server_version=version, status="ok")

    return _build_server_init_ack(
        server_version=version,
        status="version_mismatch",
        message=_build_version_mismatch_message(client_version, version),
    )


def _build_server_init_ack(
    *,
    server_version: str,
    status: str,
    message: str | None = None,
) -> dict[str, Any]:
    base = {
        "event": "server_init_ack",
        "session_id": uuid.uuid4().hex,
        "server_version": server_version,
        "status": status,
        "timestamp": int(time.time()),
    }
    if message is None:
        return base
    return {**base, "message": message}


def _build_version_mismatch_message(client_version: str, server_version: str) -> str:
    return (
        f"Client version {client_version} is incompatible with "
        f"server version {server_version}: MAJOR version mismatch"
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


def _load_contract_events(
    manifest_path: Path,
    event_configs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        event_name: {
            **event_config,
            "schema": _read_json(manifest_path.parent / event_config["schema"]),
        }
        for event_name, event_config in event_configs.items()
    }


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
def _resolve_contracts_root() -> Path:
    resolved_path = Path(__file__).resolve()
    candidates = [Path("/contracts")]
    project_root = _resolve_project_root(resolved_path)
    if project_root is not None:
        candidates.append(project_root / "contracts")

    contracts_root = _first_existing_path(candidates)
    if contracts_root is not None:
        return contracts_root
    raise ProtocolValidationError(
        "Contracts directory not found",
        version=DEFAULT_PROTOCOL_VERSION,
    )


@lru_cache(maxsize=1)
def _resolve_protocol_root() -> Path:
    return _require_existing_path(
        _resolve_contracts_root() / "schemas",
        message="Protocol schema directory not found",
    )


def _resolve_project_root(resolved_path: Path) -> Path | None:
    if len(resolved_path.parents) < 4:
        return None
    return resolved_path.parents[3]


def _resolve_generated_python_root() -> Path:
    generated_python_root = _resolve_contracts_root() / "generated" / "python"
    if generated_python_root.exists():
        return generated_python_root
    raise ModuleNotFoundError(f"Generated protocol contracts not found: {generated_python_root}")


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _require_existing_path(path: Path, *, message: str) -> Path:
    if path.exists():
        return path
    raise ProtocolValidationError(
        message,
        version=DEFAULT_PROTOCOL_VERSION,
    )


_ensure_generated_contracts_import_path()

from openvman_contracts.protocol_contracts import (  # noqa: E402
    CLIENT_EVENT_ADAPTER,
    SERVER_EVENT_ADAPTER,
    ClientInitEvent,
    ClientInterruptEvent,
    ProtocolDirection,
    ServerErrorEvent,
    ServerInitAckEvent,
    ServerStreamChunkEvent,
    UserSpeakEvent,
)
