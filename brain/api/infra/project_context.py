"""Project-scoped context: paths, DB connections, and session stores."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import lancedb

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "projects"


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """Immutable resolved paths for a single project."""

    project_id: str
    project_root: Path
    workspace_root: Path
    lancedb_path: Path
    session_db_path: Path
    index_state_path: Path


def normalize_project_id(project_id: str | None) -> str:
    """Validate and normalize a project ID. Empty/None -> 'default'."""
    text = (project_id or "").strip() or "default"
    if not _PROJECT_ID_RE.match(text):
        raise ValueError("project_id 格式不合法 (僅允許英數字、點、底線、連字號，1-64 字元)")
    return text


def resolve_project_context(project_id: str | None = None) -> ProjectContext:
    """Resolve all paths for a given project."""
    pid = normalize_project_id(project_id)
    root = _DATA_ROOT / pid
    return ProjectContext(
        project_id=pid,
        project_root=root,
        workspace_root=root / "workspace",
        lancedb_path=root / "lancedb",
        session_db_path=root / "sessions.db",
        index_state_path=root / "knowledge_index_state.json",
    )


# ---------------------------------------------------------------------------
# Per-project LanceDB connection cache
# ---------------------------------------------------------------------------

_db_cache: dict[str, Any] = {}
_db_lock = Lock()


def get_project_db(ctx: ProjectContext) -> Any:
    """Return a cached LanceDB connection for the given project."""
    if ctx.project_id in _db_cache:
        return _db_cache[ctx.project_id]

    with _db_lock:
        if ctx.project_id in _db_cache:
            return _db_cache[ctx.project_id]

        import lancedb

        ctx.lancedb_path.parent.mkdir(parents=True, exist_ok=True)
        conn = lancedb.connect(str(ctx.lancedb_path))
        _db_cache[ctx.project_id] = conn
        return conn


# ---------------------------------------------------------------------------
# Per-project SessionStore cache
# ---------------------------------------------------------------------------

_session_store_cache: dict[str, Any] = {}
_session_store_lock = Lock()


def get_project_session_store(ctx: ProjectContext):
    """Return a cached SessionStore for the given project."""
    if ctx.project_id in _session_store_cache:
        return _session_store_cache[ctx.project_id]

    with _session_store_lock:
        if ctx.project_id in _session_store_cache:
            return _session_store_cache[ctx.project_id]

        from memory.session_store import SessionStore

        store = SessionStore(db_path=str(ctx.session_db_path))
        _session_store_cache[ctx.project_id] = store
        return store


def generate_project_id(label: str) -> str:
    """從用戶輸入的名稱自動產生 project_id。"""
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower().strip()).strip("-")
    suffix = hashlib.sha256(label.encode()).hexdigest()[:10]
    if slug and len(slug) <= 50:
        return f"{slug}-{suffix}"
    return f"proj-{suffix}"


def get_data_root() -> Path:
    """Return the data/projects root directory."""
    return _DATA_ROOT


def reset_caches() -> None:
    """Clear all cached connections and stores. For testing only."""
    global _db_cache, _session_store_cache
    with _db_lock:
        _db_cache = {}
    with _session_store_lock:
        _session_store_cache = {}
