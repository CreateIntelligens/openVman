"""A request's tools must remain scoped while another project synchronizes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event


def _write_skill(directory: Path, name: str):
    directory.mkdir(parents=True)
    (directory / "skill.yaml").write_text(
        f"id: {name}\nname: {name}\ndescription: test\ntools:\n"
        "  - name: act\n    description: act\n"
        "    parameters: {type: object, properties: {}}\n"
    )
    (directory / "main.py").write_text("def act(args):\n    return {'ok': True}\n")


def test_request_registry_does_not_change_when_other_project_syncs(monkeypatch, tmp_path):
    from tools import skill_manager, tool_registry

    shared, projects = tmp_path / "shared", tmp_path / "projects"
    shared.mkdir()
    _write_skill(projects / "alpha" / "skills" / "alpha", "alpha")
    _write_skill(projects / "beta" / "skills" / "beta", "beta")
    manager = skill_manager.SkillManager(str(shared), str(projects))
    manager.scan_and_load_skills()
    monkeypatch.setattr(skill_manager, "get_skill_manager", lambda: manager)
    monkeypatch.setattr(tool_registry, "_registry", tool_registry.ToolRegistry())
    monkeypatch.setattr(tool_registry, "_sync_invalidated", True)
    monkeypatch.setattr(tool_registry, "_last_synced_project", None)
    monkeypatch.setattr(tool_registry, "_last_skill_revision", None)
    alpha_ready, beta_done = Event(), Event()

    def alpha_request():
        with tool_registry.bind_tool_context("default", "alpha"):
            registry = tool_registry.get_tool_registry()
            alpha_ready.set()
            assert beta_done.wait(timeout=10)
            return {tool.name for tool in registry.list_tools()}

    def beta_request():
        assert alpha_ready.wait(timeout=10)
        try:
            with tool_registry.bind_tool_context("default", "beta"):
                registry = tool_registry.get_tool_registry()
                return {tool.name for tool in registry.list_tools()}
        finally:
            beta_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        alpha = pool.submit(alpha_request)
        beta = pool.submit(beta_request)
        assert beta.result(timeout=15) == {"proj:beta:beta:act"}
        assert alpha.result(timeout=15) == {"proj:alpha:alpha:act"}
