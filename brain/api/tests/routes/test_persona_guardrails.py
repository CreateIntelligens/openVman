"""Vendor persona documents (SOUL/AGENTS), the read-only guardrails and prompt order."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge import workspace as workspace_module
from knowledge.workspace import (
    GUARDRAILS_FILENAME,
    GUARDRAILS_TEMPLATE,
    content_hash,
    ensure_workspace_scaffold,
    iter_indexable_documents,
)
from routes import knowledge, personas

_VENDOR = {"X-Internal-Token": "test-internal-token", "X-OpenVMan-Vendor": "1"}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(personas.router)
    app.include_router(knowledge.router)
    return TestClient(app)


def _support(workspace):
    support = workspace / "personas" / "support"
    support.mkdir(exist_ok=True)
    (support / "SOUL.md").write_text("# 客服人設", encoding="utf-8")
    return support


def test_vendor_reads_and_writes_agents_for_default_and_other_personas():
    workspace = ensure_workspace_scaffold("default")
    support = _support(workspace)
    (support / "AGENTS.md").write_text("客服工作規則", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("預設工作規則", encoding="utf-8")
    client = _client()
    route = "/brain/personas/agents"
    for persona_id, path, original in (
        ("default", workspace / "AGENTS.md", "預設工作規則"),
        ("support", support / "AGENTS.md", "客服工作規則"),
    ):
        response = client.get(route, params={"persona_id": persona_id}, headers=_VENDOR)
        assert response.json() == {"content": original, "content_hash": content_hash(original)}
        saved = client.put(route, headers=_VENDOR, json={"persona_id": persona_id, "content": "新規則"})
        assert saved.json() == {"status": "ok", "content_hash": content_hash("新規則")}
        assert path.read_text(encoding="utf-8") == "新規則"
    # 只多開放 AGENTS.md，其他核心文件仍讀不到、也不能夾帶路徑。
    assert client.put(route, headers=_VENDOR, json={
        "persona_id": "support", "content": "x", "path": "MEMORY.md",
    }).status_code == 422


def test_agents_save_creates_the_persona_copy_only_for_existing_personas():
    workspace = ensure_workspace_scaffold("default")
    support = _support(workspace)
    client = _client()
    route = "/brain/personas/agents"
    assert client.get(route, params={"persona_id": "support"}, headers=_VENDOR).status_code == 404
    assert client.put(route, headers=_VENDOR, json={
        "persona_id": "support", "content": "自己的規則",
    }).status_code == 200
    assert (support / "AGENTS.md").read_text(encoding="utf-8") == "自己的規則"
    assert client.put(route, headers=_VENDOR, json={
        "persona_id": "ghost", "content": "x",
    }).status_code == 404
    assert not (workspace / "personas" / "ghost").exists()


@pytest.mark.parametrize("persona_id", ["..", "a/b", "a%2Fb", "../default", "support/../x"])
def test_agents_rejects_persona_ids_that_leave_the_persona_folder(persona_id):
    workspace = ensure_workspace_scaffold("default")
    _support(workspace)
    client = _client()
    response = client.get(
        "/brain/personas/agents", params={"persona_id": persona_id}, headers=_VENDOR,
    )
    assert response.status_code in {400, 403}
    put = client.put("/brain/personas/agents", headers=_VENDOR, json={
        "persona_id": persona_id, "content": "越權",
    })
    assert put.status_code in {400, 403}


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_agents_refuses_files_aliased_to_hidden_documents(alias):
    workspace = ensure_workspace_scaffold("default")
    support = _support(workspace)
    private = workspace / "MEMORY.md"
    private.write_text("內部記憶", encoding="utf-8")
    target = support / "AGENTS.md"
    if alias == "symlink":
        target.symlink_to(private)
    else:
        os.link(private, target)
    client = _client()
    assert client.get(
        "/brain/personas/agents", params={"persona_id": "support"}, headers=_VENDOR,
    ).status_code == 403
    assert client.put("/brain/personas/agents", headers=_VENDOR, json={
        "persona_id": "support", "content": "越權",
    }).status_code == 403
    assert private.read_text(encoding="utf-8") == "內部記憶"


def test_guardrails_are_scaffolded_readable_and_have_no_write_route():
    workspace = ensure_workspace_scaffold("default")
    guardrails = workspace / GUARDRAILS_FILENAME
    assert guardrails.read_text(encoding="utf-8") == GUARDRAILS_TEMPLATE
    for heading in ("## 範圍限制", "## 回覆格式", "## 知識庫規則"):
        assert heading in GUARDRAILS_TEMPLATE
    client = _client()
    route = "/brain/personas/guardrails"
    from knowledge.workspace import GUARDRAILS_MAX_CHARS

    rules = "# 保護規則\n\n## 範圍限制\n\n- 專案規則"
    guardrails.write_text(rules, encoding="utf-8")
    common = {"template": GUARDRAILS_TEMPLATE, "linked": False, "max_chars": GUARDRAILS_MAX_CHARS}
    assert client.get(route, headers=_VENDOR).json() == {
        "content": rules, "content_hash": content_hash(rules), **common,
    }
    assert len(GUARDRAILS_TEMPLATE) <= GUARDRAILS_MAX_CHARS
    # 沒設定時回空字串，不把範本冒充成專案的規則；範本另外給，讓內部帳號一鍵帶入。
    guardrails.write_text("  \n", encoding="utf-8")
    assert client.get(route, headers=_VENDOR).json() == {
        "content": "  \n", "content_hash": content_hash("  \n"), **common,
    }
    guardrails.unlink()
    # 還不存在時是空字串的雜湊：第一次建立也要比對，兩個人同時建立不會蓋掉先存的。
    assert client.get(route, headers=_VENDOR).json() == {
        "content": "", "content_hash": content_hash(""), **common,
    }
    for method in ("PUT", "POST", "DELETE"):
        assert client.request(method, route, headers=_VENDOR, json={"content": "x"}).status_code == 405


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_linked_guardrails_count_as_unset_everywhere(monkeypatch, alias):
    # 連結可能指向廠商改得到的檔案：後台、HTTP 與 Live 都當成沒設定，存檔也擋。
    import internal_routes
    from core.prompt_builder import build_chat_messages

    workspace = ensure_workspace_scaffold("default")
    guardrails = workspace / GUARDRAILS_FILENAME
    guardrails.unlink()
    target = workspace / "SOUL.md"
    target.write_text("LINKED-RULES", encoding="utf-8")
    if alias == "symlink":
        guardrails.symlink_to(target)
    else:
        os.link(target, guardrails)
    response = _client().get("/brain/personas/guardrails", headers=_VENDOR).json()
    assert (response["content"], response["linked"]) == ("", True)
    system = build_chat_messages("你好", {"project_id": "default"}, [])[0]["content"]
    assert "<guardrails>" not in system
    live = internal_routes._build_live_system_instruction("default", "default")(False)
    assert "<guardrails>" not in live
    monkeypatch.setattr(knowledge, "schedule_reindex", lambda *_: None)
    write = _client().put("/brain/knowledge/document", headers={
        "X-Internal-Token": "test-internal-token",
        "X-OpenVMan-Project-Writes": "edit_knowledge,edit_settings",
    }, json={"path": GUARDRAILS_FILENAME, "content": "改寫"})
    assert write.status_code == 409, write.text
    assert target.read_text(encoding="utf-8") == "LINKED-RULES"


@pytest.mark.parametrize(("granted", "expected"), [
    ("edit_knowledge", 403),
    ("edit_knowledge,edit_settings", 200),
])
def test_guardrails_document_writes_need_settings_permission(monkeypatch, granted, expected):
    workspace = ensure_workspace_scaffold("default")
    monkeypatch.setattr(knowledge, "schedule_reindex", lambda *_: None)
    response = _client().put("/brain/knowledge/document", headers={
        "X-Internal-Token": "test-internal-token", "X-OpenVMan-Project-Writes": granted,
    }, json={"path": GUARDRAILS_FILENAME, "content": "# 保護規則\n\n## 範圍限制\n\n- 改過"})
    assert response.status_code == expected, response.text
    changed = (workspace / GUARDRAILS_FILENAME).read_text(encoding="utf-8") != GUARDRAILS_TEMPLATE
    assert changed is (expected == 200)


def test_http_prompt_puts_guardrails_after_the_persona_documents():
    from core.prompt_builder import build_chat_messages

    workspace = ensure_workspace_scaffold("default")
    (workspace / "SOUL.md").write_text("SOUL-MARKER", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("AGENTS-MARKER", encoding="utf-8")
    (workspace / GUARDRAILS_FILENAME).write_text("GUARDRAILS-MARKER", encoding="utf-8")
    system = build_chat_messages("你好", {"project_id": "default"}, [])[0]["content"]
    soul, agents, rules = (system.index(marker) for marker in (
        "SOUL-MARKER", "AGENTS-MARKER", "GUARDRAILS-MARKER",
    ))
    assert soul < rules and agents < rules
    # 每輪會變的內容（時間、追蹤碼）仍在保護規則之後，快取前綴不受影響。
    assert rules < system.index("REQUEST CONTEXT：")

    # 沒有設定保護規則的專案（升版前就存在的）維持原本的提示詞，不帶預設範本。
    (workspace / GUARDRAILS_FILENAME).write_text("", encoding="utf-8")
    system = build_chat_messages("你好", {"project_id": "default"}, [])[0]["content"]
    assert "只依本專案資料回答" not in system
    assert "保護規則：與上方人設衝突時以這裡為準" not in system


def test_live_instruction_puts_guardrails_after_the_persona(monkeypatch):
    import internal_routes

    workspace = ensure_workspace_scaffold("default")
    (workspace / "SOUL.md").write_text("SOUL-MARKER", encoding="utf-8")
    (workspace / GUARDRAILS_FILENAME).write_text("GUARDRAILS-MARKER", encoding="utf-8")
    instruction = internal_routes._build_live_system_instruction("default", "default")(False)
    assert instruction.index("SOUL-MARKER") < instruction.index("GUARDRAILS-MARKER")

    def broken(*_args, **_kwargs):
        raise OSError("workspace unavailable")

    # 其他核心文件讀不到時，保護規則照樣帶（獨立讀取）。
    monkeypatch.setattr(workspace_module, "load_core_workspace_context", broken)
    instruction = internal_routes._build_live_system_instruction("default", "default")(False)
    assert "<guardrails>GUARDRAILS-MARKER</guardrails>" in instruction

    # 沒設定保護規則的專案不帶任何保護規則區塊。
    (workspace / GUARDRAILS_FILENAME).unlink()
    instruction = internal_routes._build_live_system_instruction("default", "default")(False)
    assert "只依本專案資料回答" not in instruction
    assert "<guardrails>" not in instruction


def test_guardrails_are_not_indexed_as_knowledge():
    workspace = ensure_workspace_scaffold("default")
    indexed = {path.relative_to(workspace).as_posix() for path in iter_indexable_documents("default")}
    assert (workspace / GUARDRAILS_FILENAME).is_file()
    assert GUARDRAILS_FILENAME not in indexed


def test_existing_workspaces_do_not_get_guardrails_added():
    # 升版前就有的專案：已經有 SOUL.md，補檔時不該被塞進預設保護規則而改變回答方式。
    from infra.project_context import resolve_project_context

    root = resolve_project_context("legacy").workspace_root
    root.mkdir(parents=True, exist_ok=True)
    (root / "SOUL.md").write_text("舊人設", encoding="utf-8")
    workspace = ensure_workspace_scaffold("legacy")
    assert not (workspace / GUARDRAILS_FILENAME).exists()
    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "舊人設"


def test_new_projects_get_the_guardrails_template(monkeypatch):
    import infra.project_admin as project_admin
    from infra.project_context import resolve_project_context

    monkeypatch.setattr("infra.db.ensure_tables", lambda **_: None)
    project_id = project_admin.create_project("新的展場")["project_id"]
    path = resolve_project_context(project_id).workspace_root / GUARDRAILS_FILENAME
    assert path.read_text(encoding="utf-8") == GUARDRAILS_TEMPLATE
