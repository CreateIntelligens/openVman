"""Video-to-bundle jobs: hand a silent clip to the avatar-pipeline worker.

The backend owns the job record (who asked, which char_id, which project)
and the pipeline merges progress into the same Redis document. Both
containers mount ``./data`` at ``/data`` so the source and output paths in
the record mean the same thing on either side. Finalization — turning the
finished bundle into a character — happens here, lazily, when an admin
reads a job that the worker has marked done.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.auth.models import ResourceType, ResourceVisibility
from app.auth.runtime import AuthRuntime
from app.avatar.store import AvatarStore, CharacterExists
from app.config import get_tts_config
from app.gateway.queue import get_arq_pool
from app.gateway.redis_pool import get_redis

logger = logging.getLogger("backend.avatar.jobs")

# 與 avatar-pipeline/pipeline/status.py、worker.py 共用；改這裡要一起改那邊。
JOB_KEY_PREFIX = "vman:avatar-pipeline:job:"
JOB_TTL_SECONDS = 24 * 60 * 60
QUEUE_NAME = "vman:avatar-pipeline"
JOB_FUNCTION = "build_avatar_bundle"

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"

SOURCE_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm")
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"
_PUBLIC_FIELDS = (
    "job_id", "state", "stage", "done", "total", "error",
    "char_id", "label", "project_id", "source_name",
    "created_at", "updated_at", "frame_count", "width", "height",
    "character",
)


class InvalidSource(ValueError):
    """The uploaded clip is not a container the pipeline can read."""


class QueueUnavailable(RuntimeError):
    """Redis or the arq pool is down; the job cannot be accepted."""


def validate_source_bytes(data: bytes, *, filename: str) -> str:
    """Return the normalized extension or raise ``InvalidSource``."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SOURCE_EXTENSIONS:
        raise InvalidSource("影片必須是 .mp4、.mov、.m4v 或 .webm 檔")
    if suffix == ".webm":
        if not data.startswith(_EBML_MAGIC):
            raise InvalidSource("影片內容不是有效的 webm")
    elif data[4:8] != b"ftyp":
        raise InvalidSource("影片內容不是有效的 MP4／MOV")
    return suffix


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {k: record[k] for k in _PUBLIC_FIELDS if k in record}


@dataclass(frozen=True)
class JobPaths:
    root: Path
    source: Path
    output: Path


def job_paths(job_id: str, suffix: str = ".mp4") -> JobPaths:
    root = Path(get_tts_config().avatar_jobs_dir) / job_id
    return JobPaths(root=root, source=root / f"source{suffix}", output=root / "out")


async def _read(redis: Any, job_id: str) -> dict[str, Any] | None:
    raw = await redis.get(_job_key(job_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


async def _write(redis: Any, record: dict[str, Any]) -> None:
    record["updated_at"] = time.time()
    await redis.set(_job_key(record["job_id"]), json.dumps(record), ex=JOB_TTL_SECONDS)


async def submit_job(
    *,
    char_id: str,
    label: str,
    project_id: str | None,
    visibility: ResourceVisibility,
    created_by: str,
    source_name: str,
    source_bytes: bytes,
) -> dict[str, Any]:
    """Persist the clip, record the job and enqueue it for the worker."""
    suffix = validate_source_bytes(source_bytes, filename=source_name)
    redis = await get_redis()
    pool = await get_arq_pool()
    if redis is None or pool is None:
        raise QueueUnavailable("素材包轉換佇列目前無法使用")

    job_id = uuid.uuid4().hex
    paths = job_paths(job_id, suffix)
    paths.output.mkdir(parents=True, exist_ok=False)
    paths.source.write_bytes(source_bytes)

    record = {
        "job_id": job_id,
        "state": STATE_QUEUED,
        "stage": STATE_QUEUED,
        "char_id": char_id,
        "label": label,
        "project_id": project_id,
        "visibility": visibility.value,
        "created_by": created_by,
        "source_name": Path(source_name).name,
        "created_at": time.time(),
        "input_path": str(paths.source),
        "output_dir": str(paths.output),
    }
    await _write(redis, record)
    try:
        await pool.enqueue_job(
            JOB_FUNCTION,
            {"job_id": job_id, "input_path": record["input_path"], "output_dir": record["output_dir"]},
            _job_id=job_id,
            _queue_name=QUEUE_NAME,
        )
    except Exception as exc:
        shutil.rmtree(paths.root, ignore_errors=True)
        await redis.delete(_job_key(job_id))
        raise QueueUnavailable(f"無法排入轉換佇列：{exc}") from exc
    logger.info("avatar_job_enqueued job_id=%s char_id=%s", job_id, char_id)
    return _public(record)


def _finalize(
    record: dict[str, Any], store: AvatarStore, runtime: AuthRuntime,
) -> dict[str, Any]:
    """Move a finished bundle into the character store and register it."""
    output = Path(record["output_dir"])
    video = output / "01.webm"
    data = output / "combined_data.json.gz"
    if not (video.is_file() and data.is_file()):
        record["state"] = STATE_FAILED
        record["error"] = "轉換完成但找不到輸出檔"
        return record
    try:
        character = store.create_character(
            char_id=record["char_id"],
            label=record.get("label") or "",
            video_bytes=video.read_bytes(),
            data_bytes=data.read_bytes(),
        )
    except CharacterExists as exc:
        record["state"] = STATE_FAILED
        record["error"] = str(exc)
        return record
    project_id = record.get("project_id") or None
    try:
        runtime.resources.register(
            resource_type=ResourceType.AVATAR_CHARACTER,
            resource_id=record["char_id"],
            owner_user_id=None,
            visibility=ResourceVisibility(record.get("visibility") or ResourceVisibility.SYSTEM_PUBLIC.value),
            owner_project_id=project_id,
            metadata={"label": record["label"]} if record.get("label") else {},
        )
    except Exception:  # noqa: BLE001 - 登錄失敗不該讓已建好的角色消失
        logger.exception("avatar_job_register_failed job_id=%s", record["job_id"])
    record["character"] = character
    record["registered"] = True
    shutil.rmtree(Path(record["output_dir"]).parent, ignore_errors=True)
    return record


async def get_job(
    job_id: str, *, store: AvatarStore, runtime: AuthRuntime,
) -> dict[str, Any] | None:
    redis = await get_redis()
    if redis is None:
        raise QueueUnavailable("素材包轉換佇列目前無法使用")
    record = await _read(redis, job_id)
    if record is None:
        return None
    if record.get("state") == STATE_DONE and not record.get("registered"):
        record = _finalize(record, store, runtime)
        await _write(redis, record)
    return _public(record)


async def list_jobs(*, store: AvatarStore, runtime: AuthRuntime) -> list[dict[str, Any]]:
    redis = await get_redis()
    if redis is None:
        raise QueueUnavailable("素材包轉換佇列目前無法使用")
    jobs: list[dict[str, Any]] = []
    async for key in redis.scan_iter(match=f"{JOB_KEY_PREFIX}*"):
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        job_id = key[len(JOB_KEY_PREFIX):]
        record = await get_job(job_id, store=store, runtime=runtime)
        if record is not None:
            jobs.append(record)
    jobs.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
    return jobs


async def delete_job(job_id: str) -> bool:
    """Drop the record and any leftover files once the worker is done with it.

    A queued job is still in the arq queue; deleting its files now would make
    the worker fail later and recreate a record with no char_id.
    """
    redis = await get_redis()
    if redis is None:
        raise QueueUnavailable("素材包轉換佇列目前無法使用")
    record = await _read(redis, job_id)
    if record is None:
        return False
    if record.get("state") in (STATE_QUEUED, STATE_RUNNING):
        raise RuntimeError("工作還沒跑完，無法刪除")
    if record.get("output_dir"):
        shutil.rmtree(Path(record["output_dir"]).parent, ignore_errors=True)
    await redis.delete(_job_key(job_id))
    return True
