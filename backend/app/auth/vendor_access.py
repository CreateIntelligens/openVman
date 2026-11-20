"""HTTP routes exposed to a vendor account, after authentication."""

import re
from collections.abc import Mapping
from typing import Any

VENDOR_HEADER = "X-OpenVMan-Vendor"

# File operations from the knowledge page use a separate URL namespace.
# The upstream can share its implementation because it also checks the resolved path.
KNOWLEDGE_DOCUMENT_ROUTES = {
    "/knowledge/base/document": "/knowledge/document",
    "/knowledge/base/document/meta": "/knowledge/document/meta",
    "/knowledge/base/directory": "/knowledge/directory",
    "/knowledge/base/move": "/knowledge/move",
}

_GET = frozenset({
    "/auth/me", "/auth/admin-me", "/projects", "/uploads/limits",
    "/personas", "/personas/soul", "/personas/agents", "/personas/guardrails",
    "/chat/history", "/chat/modes", "/sessions", "/sessions/export",
    "/knowledge/base/documents", "/knowledge/base/document", "/knowledge/qa",
    "/knowledge/qa/questions", "/knowledge/qa/nodes", "/knowledge/qa/sync-status",
    "/knowledge/qa/export",
    "/knowledge/settings", "/knowledge/raw/pending", "/knowledge/raw/commit/status",
})
_POST = frozenset({
    "/auth/logout", "/auth/password",
    "/chat", "/chat/stream", "/chat/accept",
    "/knowledge/base/directory", "/knowledge/base/move", "/knowledge/note",
    "/knowledge/upload", "/knowledge/raw/upload", "/knowledge/raw/commit",
    "/knowledge/fetch",
    "/knowledge/qa/nodes", "/knowledge/qa/nodes/adopt-source",
    "/knowledge/qa/images",
})
# 廠商可改個性與說話方式（SOUL.md）與工作規則（AGENTS.md）；保護規則只讀。
_PUT = frozenset({
    "/personas/soul", "/personas/agents", "/knowledge/base/document", "/knowledge/settings",
})
_DELETE = frozenset({
    "/knowledge/base/document", "/knowledge/base/directory", "/knowledge/raw/pending",
})
_ROUTES: Mapping[str, frozenset[str]] = {
    "GET": _GET,
    "POST": _POST,
    "PUT": _PUT,
    "PATCH": frozenset({"/knowledge/base/document/meta"}),
    "DELETE": _DELETE,
}
_PROJECT_DETAIL = re.compile(r"/projects/[^/]+")
_QA_RESOURCE = re.compile(r"/knowledge/qa/(nodes|images)/([^/]+)(?:/([^/]+))?")
_QA_METHODS = {
    ("nodes", None): frozenset({"PATCH", "DELETE"}),
    ("nodes", "merged"): frozenset({"GET", "PUT"}),
    ("nodes", "entries"): frozenset({"POST", "DELETE"}),
    ("nodes", "move"): frozenset({"POST"}),
    ("nodes", "reorder"): frozenset({"POST"}),
    ("nodes", "ingest-source"): frozenset({"POST"}),
    ("images", None): frozenset({"GET", "DELETE"}),
}


def vendor_route_allowed(method: str, path: str) -> bool:
    if not path.startswith("/api/v1/"):
        return False
    path = path.removeprefix("/api/v1")
    if method == "GET" and _PROJECT_DETAIL.fullmatch(path):
        return True
    if path in _ROUTES.get(method, ()):
        return True
    match = _QA_RESOURCE.fullmatch(path)
    if match is None:
        return False
    kind, identifier, action = match.groups()
    return identifier not in {".", ".."} and method in _QA_METHODS.get((kind, action), ())


def is_vendor_knowledge_path(value: Any) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    parts = value.split("/")
    return len(parts) >= 2 and parts[0] == "knowledge" and all(
        part and not part.startswith(".") and part not in {"graphify-out", "_catalog.yaml"}
        for part in parts[1:]
    )
