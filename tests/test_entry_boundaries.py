"""Keep composition roots small and domain behavior in owned modules."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    "backend/app",
    "brain/api",
    "brain/embedding",
    "brain/skills",
    "frontend/app/src",
    "frontend/admin/src",
    "frontend/shared",
    "frontend/avatar-sdk/src",
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".vue", ".css"}
EXCLUDED_DIRS = {
    "__pycache__", "__tests__", "tests", "node_modules", "vendor", "assets",
}


@pytest.mark.parametrize("path", ("backend/app/main.py", "brain/api/main.py"))
def test_python_entrypoints_only_define_server_bootstrap(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    definitions = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert set(definitions) <= {"run_server", "create_app"}, (
        f"{path} must delegate routes, lifecycle and domain behavior: {definitions}"
    )
    route_decorators = [
        ast.unparse(decorator)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if re.match(r"app\.(get|post|put|delete|patch|websocket)\(",
                    ast.unparse(decorator))
    ]
    assert not route_decorators, f"Move inline routes out of {path}"


def test_backend_catch_all_is_registered_after_specific_routes():
    tree = ast.parse((ROOT / "backend/app/main.py").read_text(encoding="utf-8"))
    registrations = [
        node.value.args[0]
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func) == "app.include_router"
    ]
    assert registrations, "Backend must register its routes"
    assert ast.unparse(registrations[-1]) == "brain_proxy_router", (
        "The Brain catch-all would shadow specific ASR/TTS routes"
    )


def test_avatar_app_delegates_voice_and_browser_lifecycle():
    source = (ROOT / "frontend/app/src/App.vue").read_text(encoding="utf-8")
    match = re.search(r"<script\b[^>]*>([\s\S]*?)</script>", source)
    assert match, "Avatar App must have a composition script"
    script = match.group(1)
    assert len(script.splitlines()) <= 200, "Keep App.vue as a composition root"
    assert not re.search(r"\b(setTimeout|setInterval|fetch)\s*\(", script), (
        "Timers and requests belong to the responsible composable"
    )
    assert not re.search(r"\bfunction\s+(scheduleAsr|handleAsr|handleSend)", script), (
        "Speech input and reply policy must not return to App.vue"
    )


def test_owned_production_sources_stay_under_one_thousand_lines():
    oversized = []
    for source_root in SOURCE_ROOTS:
        for path in (ROOT / source_root).rglob("*"):
            if (
                not path.is_file()
                or path.suffix not in SOURCE_SUFFIXES
                or EXCLUDED_DIRS.intersection(path.relative_to(ROOT).parts)
                or path.name.startswith("test_")
                or ".test." in path.name
                or ".spec." in path.name
            ):
                continue
            count = len(path.read_text(encoding="utf-8").splitlines())
            if count > 1000:
                oversized.append(f"{path.relative_to(ROOT)}: {count}")
    assert not oversized, "Split by responsibility:\n" + "\n".join(oversized)
