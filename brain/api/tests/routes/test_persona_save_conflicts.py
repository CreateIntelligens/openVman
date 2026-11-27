"""Hash-checked saves of SOUL.md, AGENTS.md and GUARDRAILS.md: stale editors get 409."""

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge.workspace import GUARDRAILS_FILENAME, content_hash, ensure_workspace_scaffold
from routes import knowledge, personas

_INTERNAL = {"X-Internal-Token": "test-internal-token"}
_VENDOR = {**_INTERNAL, "X-OpenVMan-Vendor": "1"}
_SETTINGS = {**_INTERNAL, "X-OpenVMan-Project-Writes": "edit_knowledge,edit_settings"}
_STALE = "這份文件在你編輯時被改過了，請重新載入後再存檔"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(knowledge, "schedule_reindex", lambda *_: None)
    app = FastAPI()
    app.include_router(personas.router)
    app.include_router(knowledge.router)
    return TestClient(app)


def _support(workspace):
    support = workspace / "personas" / "support"
    support.mkdir(exist_ok=True)
    (support / "SOUL.md").write_text("# 客服人設", encoding="utf-8")
    return support


def test_empty_hash_matches_the_admin_constant():
    # 後台 api/personas.ts 的 EMPTY_CONTENT_HASH：檔案還不存在時存檔帶這個值。
    assert content_hash("") == "e3b0c44298fc1c14"


@pytest.mark.parametrize("route", ["/brain/personas/soul", "/brain/personas/agents"])
@pytest.mark.parametrize("headers", [_INTERNAL, _VENDOR], ids=["internal", "vendor"])
def test_stale_base_hash_is_refused_and_keeps_the_newer_file(client, route, headers):
    workspace = ensure_workspace_scaffold("default")
    path = workspace / f"{route.rsplit('/', 1)[1].upper()}.md"
    path.write_text("原本", encoding="utf-8")
    loaded = client.get(route, headers=headers).json()
    assert loaded == {"content": "原本", "content_hash": content_hash("原本")}

    first = client.put(route, headers=headers, json={"content": "分頁一", "base_hash": loaded["content_hash"]})
    assert first.status_code == 200, first.text
    assert first.json() == {"status": "ok", "content_hash": content_hash("分頁一")}
    assert client.get(route, headers=headers).json()["content_hash"] == first.json()["content_hash"]

    second = client.put(route, headers=headers, json={"content": "分頁二", "base_hash": loaded["content_hash"]})
    assert second.status_code == 409
    assert second.json()["detail"] == _STALE
    assert path.read_text(encoding="utf-8") == "分頁一"

    # 舊的呼叫方式（不帶 base_hash）照舊整份覆寫。
    legacy = client.put(route, headers=headers, json={"content": "腳本"})
    assert legacy.status_code == 200
    assert path.read_text(encoding="utf-8") == "腳本"


def test_first_agents_save_of_two_editors_wins_and_the_second_gets_409(client):
    workspace = ensure_workspace_scaffold("default")
    support = _support(workspace)
    route = "/brain/personas/agents"
    assert client.get(route, params={"persona_id": "support"}, headers=_INTERNAL).status_code == 404
    empty = content_hash("")
    first = client.put(route, headers=_INTERNAL, json={
        "persona_id": "support", "content": "甲寫的規則", "base_hash": empty,
    })
    assert first.status_code == 200, first.text
    second = client.put(route, headers=_INTERNAL, json={
        "persona_id": "support", "content": "乙寫的規則", "base_hash": empty,
    })
    assert second.status_code == 409
    assert (support / "AGENTS.md").read_text(encoding="utf-8") == "甲寫的規則"


def test_form_and_raw_mode_share_one_version_of_soul(client):
    workspace = ensure_workspace_scaffold("default")
    (workspace / "SOUL.md").write_text("原本", encoding="utf-8")
    form_hash = client.get("/brain/personas/soul", headers=_INTERNAL).json()["content_hash"]
    raw = client.get("/brain/knowledge/document", headers=_INTERNAL, params={"path": "SOUL.md"}).json()
    assert raw["content_hash"] == form_hash

    saved = client.put("/brain/knowledge/document", headers=_INTERNAL, json={
        "path": "SOUL.md", "content": "原始文件改的", "base_hash": raw["content_hash"],
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["content_hash"] == content_hash("原始文件改的")
    stale = client.put("/brain/personas/soul", headers=_INTERNAL, json={
        "content": "表格改的", "base_hash": form_hash,
    })
    assert stale.status_code == 409
    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "原始文件改的"


def test_two_first_time_guardrails_creates_do_not_lose_one(client):
    workspace = ensure_workspace_scaffold("default")
    (workspace / GUARDRAILS_FILENAME).unlink()
    loaded = client.get("/brain/personas/guardrails", headers=_INTERNAL).json()
    assert loaded["content_hash"] == content_hash("")

    body = {"path": GUARDRAILS_FILENAME, "base_hash": loaded["content_hash"]}
    first = client.put("/brain/knowledge/document", headers=_SETTINGS, json={**body, "content": "甲的規則"})
    assert first.status_code == 200, first.text
    second = client.put("/brain/knowledge/document", headers=_SETTINGS, json={**body, "content": "乙的規則"})
    assert second.status_code == 409
    assert second.json()["detail"] == _STALE
    assert (workspace / GUARDRAILS_FILENAME).read_text(encoding="utf-8") == "甲的規則"


def test_concurrent_saves_with_the_same_base_hash_let_only_one_through(client, monkeypatch):
    workspace = ensure_workspace_scaffold("default")
    (workspace / "SOUL.md").write_text("原本", encoding="utf-8")
    base = content_hash("原本")
    real_write = personas.write_text_atomic

    def slow_write(path, content):
        # 拉長比對到寫入之間的空檔：沒有鎖時兩個請求都會比對成功。
        time.sleep(0.2)
        real_write(path, content)

    monkeypatch.setattr(personas, "write_text_atomic", slow_write)
    statuses: list[int] = []

    def save(text: str) -> None:
        response = client.put("/brain/personas/soul", headers=_INTERNAL, json={"content": text, "base_hash": base})
        statuses.append(response.status_code)

    threads = [threading.Thread(target=save, args=(text,)) for text in ("一", "二")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(statuses) == [200, 409]


@pytest.mark.parametrize("content", ["甲\r\n乙\r\n", "﻿甲\n", "甲\r乙"])
def test_saved_hash_matches_the_next_read_for_crlf_and_bom(client, content):
    # 讀檔會去掉 BOM、把 CRLF 換成 LF；存檔回的雜湊若照原文算，使用者下一次存檔就會被擋。
    ensure_workspace_scaffold("default")
    soul = client.put("/brain/personas/soul", headers=_INTERNAL, json={"content": content})
    assert soul.json()["content_hash"] == client.get("/brain/personas/soul", headers=_INTERNAL).json()["content_hash"]
    again = client.put("/brain/personas/soul", headers=_INTERNAL, json={
        "content": content, "base_hash": soul.json()["content_hash"],
    })
    assert again.status_code == 200, again.text

    raw = client.put("/brain/knowledge/document", headers=_INTERNAL, json={"path": "AGENTS.md", "content": content})
    loaded = client.get("/brain/knowledge/document", headers=_INTERNAL, params={"path": "AGENTS.md"}).json()
    assert raw.json()["content_hash"] == loaded["content_hash"]
