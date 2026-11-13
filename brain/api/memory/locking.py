"""Shared lock for every memory table mutation on the local data volume."""

from infra.file_lock import file_lock
from infra.project_context import resolve_project_context


def memory_table_lock(project_id: str = "default"):
    return file_lock(resolve_project_context(project_id).project_root / "memories")
