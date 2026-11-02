"""Process-local, read-only access to the deployed knowledge search tool.

Run inside the API container. This patches only this Python process; do not use
it in the serving process or concurrently with another experiment context.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import copy
import importlib
import json
import logging
import os
from pathlib import Path
import sys
from unittest.mock import patch


_guard = None
_hook_installed = False
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_PATH_EVENTS = {
    "os.remove": (0,), "os.rmdir": (0,), "os.mkdir": (0,),
    "os.rename": (0, 1), "os.link": (0, 1), "os.symlink": (1,),
    "os.chmod": (0,), "os.chown": (0,), "os.truncate": (0,),
    "os.utime": (0,), "os.setxattr": (0,), "os.removexattr": (0,),
}

_DIR_FD_POSITIONS = {
    "os.remove": {0: 1}, "os.rmdir": {0: 1}, "os.mkdir": {0: 2},
    "os.rename": {0: 2, 1: 3}, "os.link": {0: 2, 1: 3},
    "os.symlink": {1: 2}, "os.chmod": {0: 2}, "os.chown": {0: 3},
    "os.utime": {0: 3},
}


def _resolved(path, dir_fd=None):
    if isinstance(path, int):
        path = os.readlink(f"/proc/self/fd/{path}")
    value = Path(os.fsdecode(path))
    # rmtree uses paths relative to a directory descriptor. Resolving them from
    # cwd mistakes a temporary LanceDB "data" child for production /app/data.
    if not value.is_absolute() and isinstance(dir_fd, int) and dir_fd >= 0:
        value = Path(os.readlink(f"/proc/self/fd/{dir_fd}")) / value
    return value.resolve()


def _audit(event, args):
    state = _guard
    if state is None:
        return
    if event == "open":
        _, mode, flags = args
        if not ((flags or 0) & _WRITE_FLAGS or
                isinstance(mode, str) and any(c in mode for c in "wax+")):
            return
        positions = (0,)
    else:
        positions = _PATH_EVENTS.get(event, ())
    for position in positions:
        try:
            fd_position = _DIR_FD_POSITIONS.get(event, {}).get(position)
            dir_fd = args[fd_position] if fd_position is not None else None
            path = _resolved(args[position], dir_fd)
        except (OSError, TypeError, ValueError):
            continue
        if any(path == root or root in path.parents for root in state["roots"]):
            message = f"Blocked data mutation: {event} {path}"
            state["violations"].append(message)
            raise PermissionError(message)


@contextmanager
def _write_guard(roots):
    global _guard, _hook_installed
    if _guard is not None:
        raise RuntimeError("readonly_search contexts cannot overlap")
    if not _hook_installed:
        sys.addaudithook(_audit)
        _hook_installed = True
    state = {"roots": tuple(_resolved(root) for root in roots), "violations": []}
    _guard = state
    try:
        yield state
    finally:
        _guard = None


def _manifest(root):
    # Audit hooks cannot observe native Rust writes; compare the project tree too.
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


@contextmanager
def readonly_search(project_id, persona_id="default", reply_mode="", *,
                    verify_manifest=True):
    """Yield ``search(query, *, top_k=3, threshold=.68, queries=None)``.

    Embedding helpers can be called normally inside this context. Query routes
    are cached across the six settings so every cell uses the same query vector.
    Existing FTS, language ordering, deduplication and graph expansion remain on.
    A manifest mismatch (including concurrent service changes) fails on exit.
    """
    config = importlib.import_module("config")
    db = importlib.import_module("infra.db")
    project = importlib.import_module("infra.project_context")
    retrieval = importlib.import_module("memory.retrieval")
    embedder = importlib.import_module("memory.embedder")
    knowledge = importlib.import_module("tools.builtin.knowledge_tools")
    registry = importlib.import_module("tools.tool_registry")
    thresholds = importlib.import_module("memory.thresholds")
    lancedb = importlib.import_module("lancedb")

    context = project.resolve_project_context(project_id)
    if not context.lancedb_path.is_dir():
        raise FileNotFoundError(context.lancedb_path)
    before = _manifest(context.project_root) if verify_manifest else None
    cfg = config.get_settings().model_copy(deep=True)
    original_overrides = cfg.embedding_thresholds
    route_cache, connections, failures = {}, {}, []
    original_encode = embedder.encode_query_with_fallback
    original_one = knowledge._search_one
    original_mkdir = Path.mkdir

    def existing_db(ctx):
        if ctx.project_id != context.project_id:
            raise ValueError("Experiment attempted to read another project")
        if not ctx.lancedb_path.is_dir():
            raise FileNotFoundError(ctx.lancedb_path)
        if ctx.project_id not in connections:
            connections[ctx.project_id] = lancedb.connect(str(ctx.lancedb_path))
        return connections[ctx.project_id]

    def existing_table(table_name, project_id="default", embedding_version=None):
        ctx = project.resolve_project_context(project_id)
        return existing_db(ctx).open_table(
            db.resolve_vector_table_name(table_name, embedding_version)
        )

    def cached_encode(query, *, project_id="default",
                      table_names=("knowledge", "memories")):
        key = (query, project_id, tuple(table_names))
        if key not in route_cache:
            route_cache[key] = original_encode(
                query, project_id=project_id, table_names=table_names,
            )
        return copy.deepcopy(route_cache[key])

    def checked_one(*args, **kwargs):
        try:
            return original_one(*args, **kwargs)
        except Exception as exc:
            failures.append(exc)
            raise

    def forbidden(*args, **kwargs):
        raise PermissionError("Experiment must only open existing tables")

    def existing_mkdir(path, mode=0o777, parents=False, exist_ok=False):
        # Read helpers invoke the scaffold initializer even when it already
        # exists. Skip only its proven no-op case; new directories stay blocked.
        if exist_ok and path.is_dir():
            return None
        return original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    class FailClosed(logging.Handler):
        def emit(self, record):
            if str(record.msg).startswith(("Search failed for", "graph expansion failed")):
                raise RuntimeError(record.getMessage())

    roots = ("/data", Path(project.__file__).resolve().parents[1] / "data",
             context.project_root.parent)
    with _write_guard(roots) as guard, ExitStack() as stack:
        stack.enter_context(patch.object(config, "_settings", cfg))
        stack.enter_context(patch.object(project, "get_project_db", existing_db))
        # infra.db holds an imported alias of project.get_project_db.
        stack.enter_context(patch.object(db, "get_project_db", existing_db))
        stack.enter_context(patch.object(db, "get_table", existing_table))
        stack.enter_context(patch.object(db, "ensure_tables", forbidden))
        stack.enter_context(patch.object(retrieval, "record_trace", lambda **_: None))
        stack.enter_context(patch.object(embedder, "encode_query_with_fallback", cached_encode))
        stack.enter_context(patch.object(knowledge, "_search_one", checked_one))
        stack.enter_context(patch.object(Path, "mkdir", existing_mkdir))
        handler = FailClosed()
        for logger in (retrieval.logger, knowledge.logger):
            logger.addHandler(handler)
            stack.callback(logger.removeHandler, handler)

        def search(query, *, top_k=3, threshold=.68, queries=None):
            if top_k not in (3, 5) or not 0 <= threshold <= 1:
                raise ValueError("top_k must be 3 or 5; threshold must be in [0, 1]")
            overrides = json.loads(original_overrides or "{}")
            # Retrieval follows the selected version, including fallback identities.
            versions = set(cfg.resolved_embedding_version_order)
            versions.add(cfg.resolved_embedding_active_version)
            for version in versions:
                key = thresholds.version_of(version)
                overrides.setdefault(key, {})["retrieval"] = threshold
            cfg.embedding_thresholds = json.dumps(overrides)
            failures.clear()
            try:
                with registry.bind_tool_context(
                    persona_id, project_id, user_message=query, reply_mode=reply_mode,
                ):
                    result = knowledge._search_tool(
                        "knowledge", {"queries": queries or [query], "top_k": top_k},
                    )
                if failures:
                    failure = failures[0]
                    failures.clear()
                    raise RuntimeError("Search failed; empty results are invalid") from failure
                if guard["violations"]:
                    raise RuntimeError("; ".join(guard["violations"]))
                return result
            finally:
                cfg.embedding_thresholds = original_overrides

        try:
            yield search
        finally:
            if failures:
                raise RuntimeError("Search failed during the experiment") from failures[0]
            if verify_manifest and _manifest(context.project_root) != before:
                raise RuntimeError("Project data changed during the experiment")
            if guard["violations"]:
                raise RuntimeError("; ".join(guard["violations"]))
