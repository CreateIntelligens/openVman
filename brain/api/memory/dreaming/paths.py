"""Shared path helpers and constants for the dreaming subsystem."""

from __future__ import annotations

import re
from pathlib import Path

from knowledge.workspace import get_workspace_root

DATE_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SOURCE_DREAMING = "dreaming"


def dreams_dir(project_id: str) -> Path:
    """Return the .dreams state directory for a project."""
    return get_workspace_root(project_id) / "dreaming" / ".dreams"
