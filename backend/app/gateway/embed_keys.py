"""Storage for public embed API keys."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux containers provide fcntl.
    fcntl = None  # type: ignore[assignment]


DEFAULT_CACHE_TTL_SECONDS = 60.0
KEY_PREFIX = "vman_"
STORE_VERSION = 1
DEFAULT_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "embed_keys.json"


@dataclass(slots=True)
class EmbedKeyRecord:
    key_id: str
    secret_hash: str
    tenant_id: str
    allowed_domains: list[str]
    enabled: bool
    created_at: str
    note: str = ""
    disabled_at: str | None = None


@dataclass(slots=True)
class CreatedEmbedKey:
    record: EmbedKeyRecord
    secret: str


def hash_secret(secret: str) -> str:
    """Return the persisted hash representation for an API key secret."""
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_domains(domains: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({domain.strip().lower() for domain in domains if domain.strip()})


def _extract_key_id(secret: str) -> str | None:
    if not secret.startswith(KEY_PREFIX):
        return None
    key_part = secret[len(KEY_PREFIX) :].split(".", 1)[0]
    return key_part or None


class EmbedKeyStore:
    """JSON-backed embed API key store with a short in-process cache."""

    def __init__(
        self,
        path: str | Path = DEFAULT_STORE_PATH,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = Path(path)
        self._cache_ttl_seconds = cache_ttl_seconds
        self._time_fn = time_fn
        self._lock = threading.RLock()
        self._cache_loaded_at = 0.0
        self._cache: dict[str, EmbedKeyRecord] | None = None

    def create(
        self,
        *,
        tenant_id: str,
        allowed_domains: list[str] | tuple[str, ...],
        note: str = "",
    ) -> CreatedEmbedKey:
        """Create an enabled key and return the plaintext secret once."""
        if not tenant_id.strip():
            raise ValueError("tenant_id is required")

        with self._lock:
            with self._file_lock(exclusive=True):
                records = self._read_records_unlocked()
                existing_ids = {record.key_id for record in records}
                key_id = self._new_key_id(existing_ids)
                secret = self._new_secret(key_id)
                record = EmbedKeyRecord(
                    key_id=key_id,
                    secret_hash=hash_secret(secret),
                    tenant_id=tenant_id.strip(),
                    allowed_domains=_normalize_domains(allowed_domains),
                    enabled=True,
                    created_at=_utc_now_iso(),
                    note=note,
                )
                records.append(record)
                self._write_records_unlocked(records)
                self._set_cache(records)
                return CreatedEmbedKey(record=record, secret=secret)

    def get(self, secret: str) -> EmbedKeyRecord | None:
        """Return the enabled record matching *secret*, or None."""
        key_id = _extract_key_id(secret)
        if key_id is None:
            return None

        records = self._records()
        record = records.get(key_id)
        if record is None or not record.enabled:
            return None

        if not hmac.compare_digest(record.secret_hash, hash_secret(secret)):
            return None
        return self._copy_record(record)

    def disable(self, key_id: str) -> EmbedKeyRecord | None:
        """Disable a key by id, returning the updated record or None if not found."""
        return self._set_enabled(key_id, enabled=False)

    def enable(self, key_id: str) -> EmbedKeyRecord | None:
        """Re-enable a previously disabled key by id, returning the updated record."""
        return self._set_enabled(key_id, enabled=True)

    def _set_enabled(self, key_id: str, *, enabled: bool) -> EmbedKeyRecord | None:
        with self._lock:
            with self._file_lock(exclusive=True):
                target: EmbedKeyRecord | None = None
                changed = False
                records = []
                for record in self._read_records_unlocked():
                    if record.key_id == key_id:
                        if record.enabled != enabled:
                            record = replace(
                                record,
                                enabled=enabled,
                                disabled_at=None if enabled else _utc_now_iso(),
                            )
                            changed = True
                        target = record
                    records.append(record)

                if target is None:
                    return None

                if changed:
                    self._write_records_unlocked(records)
                self._set_cache(records)
                return self._copy_record(target)

    def update(
        self,
        key_id: str,
        *,
        allowed_domains: list[str] | tuple[str, ...] | None = None,
        note: str | None = None,
    ) -> EmbedKeyRecord | None:
        """Update editable metadata for a key."""
        with self._lock:
            with self._file_lock(exclusive=True):
                updated: EmbedKeyRecord | None = None
                records = []
                for record in self._read_records_unlocked():
                    if record.key_id == key_id:
                        record = replace(
                            record,
                            allowed_domains=(
                                _normalize_domains(allowed_domains)
                                if allowed_domains is not None
                                else list(record.allowed_domains)
                            ),
                            note=record.note if note is None else note,
                        )
                        updated = record
                    records.append(record)

                if updated is None:
                    return None

                self._write_records_unlocked(records)
                self._set_cache(records)
                return self._copy_record(updated)

    def list(self) -> list[EmbedKeyRecord]:
        """List stored key records without plaintext secrets."""
        return [self._copy_record(record) for record in self._records().values()]

    def _records(self) -> dict[str, EmbedKeyRecord]:
        now = self._time_fn()
        with self._lock:
            if self._cache is not None and (now - self._cache_loaded_at) < self._cache_ttl_seconds:
                return self._copy_record_map(self._cache)

            with self._file_lock(exclusive=False):
                records = self._read_records_unlocked()
            self._set_cache(records, loaded_at=now)
            return self._copy_record_map(self._cache or {})

    def _set_cache(self, records: list[EmbedKeyRecord], *, loaded_at: float | None = None) -> None:
        self._cache = {record.key_id: self._copy_record(record) for record in records}
        self._cache_loaded_at = self._time_fn() if loaded_at is None else loaded_at

    def _read_records_unlocked(self) -> list[EmbedKeyRecord]:
        if not self._path.exists():
            return []

        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return []

        raw_records = payload.get("keys", []) if isinstance(payload, dict) else []
        records = []
        for raw in raw_records:
            if not isinstance(raw, dict):
                continue
            record = self._record_from_dict(raw)
            if record is not None:
                records.append(record)
        return records

    def _write_records_unlocked(self, records: list[EmbedKeyRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STORE_VERSION,
            "keys": [asdict(record) for record in records],
        }
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self._path)

    @contextmanager
    def _file_lock(self, *, exclusive: bool) -> Iterator[None]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(f"{self._path.suffix}.lock")
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(lock_file.fileno(), operation)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _new_key_id(self, existing_ids: set[str]) -> str:
        while True:
            key_id = f"ek_{secrets.token_urlsafe(9)}"
            if key_id not in existing_ids:
                return key_id

    def _new_secret(self, key_id: str) -> str:
        return f"{KEY_PREFIX}{key_id}.{secrets.token_urlsafe(32)}"

    def _record_from_dict(self, raw: dict[str, Any]) -> EmbedKeyRecord | None:
        try:
            return EmbedKeyRecord(
                key_id=str(raw["key_id"]),
                secret_hash=str(raw["secret_hash"]),
                tenant_id=str(raw["tenant_id"]),
                allowed_domains=_normalize_domains(list(raw.get("allowed_domains") or [])),
                enabled=bool(raw.get("enabled", True)),
                created_at=str(raw["created_at"]),
                note=str(raw.get("note") or ""),
                disabled_at=str(raw["disabled_at"]) if raw.get("disabled_at") else None,
            )
        except KeyError:
            return None

    def _copy_record_map(self, records: dict[str, EmbedKeyRecord]) -> dict[str, EmbedKeyRecord]:
        return {key_id: self._copy_record(record) for key_id, record in records.items()}

    def _copy_record(self, record: EmbedKeyRecord) -> EmbedKeyRecord:
        return replace(record, allowed_domains=list(record.allowed_domains))


_default_store = EmbedKeyStore()


def get_embed_key_store() -> EmbedKeyStore:
    """Return the process-wide embed key store."""
    return _default_store
