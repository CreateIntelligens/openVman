"""Per-category Q&A indexing sync status and reindex worker state tracking."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config import get_settings  # noqa: E402
from knowledge import qa_nodes, qa_sync_status  # noqa: E402
from knowledge.doc_meta import upsert_document_meta  # noqa: E402
from knowledge.indexer import _save_index_state, fingerprint_document  # noqa: E402
from knowledge.workspace import ensure_workspace_scaffold  # noqa: E402
from main import app  # noqa: E402
from routes import knowledge as knowledge_routes  # noqa: E402
from routes import knowledge_qa as knowledge_qa_routes  # noqa: E402


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """Isolated project workspace + TestClient with cleared in-memory reindex state."""
    knowledge_routes._reindex_state.clear()
    scheduled: list[str] = []
    monkeypatch.setattr(knowledge_qa_routes, "schedule_reindex", scheduled.append)
    workspace = ensure_workspace_scaffold("default")
    client = TestClient(
        app,
        headers={"X-Internal-Token": get_settings().gateway_internal_token},
    )
    yield workspace, client, scheduled
    knowledge_routes._reindex_state.clear()


def _write_doc(workspace: Path, relative: str, content: str, *, enabled: bool = True) -> Path:
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    upsert_document_meta(relative, "default", source_type="qa", enabled=enabled)
    return path


def _mark_indexed(workspace: Path, *relatives: str, project_id: str = "default") -> None:
    _save_index_state(
        {rel: fingerprint_document(workspace / rel) for rel in relatives},
        project_id,
    )


def _setup_worker(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(knowledge_routes, "_REINDEX_DEBOUNCE_SECONDS", 0.05)
    monkeypatch.setattr(knowledge_routes, "schedule_graph_rebuild", lambda project_id: True)
    monkeypatch.setattr(
        knowledge_routes,
        "rebuild_knowledge_index",
        lambda project_id: calls.append(project_id) or {"status": "ok"},
    )
    knowledge_routes._reindex_state.clear()


def test_synced_when_fingerprints_match_and_updating_when_pending(env):
    workspace, client, scheduled = env
    rel = "knowledge/qa/faq.md"
    doc = _write_doc(workspace, rel, "## Q1\n\nA1\n")
    _mark_indexed(workspace, rel)
    qa_nodes.create_node(
        "cat_faq",
        "常見問題",
        qa_entries=[{"question": "Q1", "source_path": rel}],
    )

    resp = client.get("/brain/knowledge/qa/sync-status", params={"project_id": "default"})
    assert resp.status_code == 200
    assert resp.json() == {"categories": {"cat_faq": "synced"}}
    assert scheduled == []

    # 改寫檔案內容讓指紋與索引不同，同時標記專案 pending。
    doc.write_text("## Q1\n\nUpdated A1\n", encoding="utf-8")
    knowledge_routes._reindex_state["default"] = {
        "task": None,
        "dirty": True,
        "running": False,
        "last_error": None,
        "finished_at": None,
    }

    resp = client.get("/brain/knowledge/qa/sync-status", params={"project_id": "default"})
    assert resp.status_code == 200
    assert resp.json() == {"categories": {"cat_faq": "updating"}}
    assert scheduled == []


def test_failed_when_stale_and_last_error_present_without_pending_or_running(env):
    workspace, client, scheduled = env
    rel = "knowledge/qa/faq.md"
    doc = _write_doc(workspace, rel, "## Q1\n\nA1\n")
    _mark_indexed(workspace, rel)
    qa_nodes.create_node(
        "cat_faq",
        "常見問題",
        qa_entries=[{"question": "Q1", "source_path": rel}],
    )

    doc.write_text("## Q1\n\nChanged\n", encoding="utf-8")
    knowledge_routes._reindex_state["default"] = {
        "task": None,
        "dirty": False,
        "running": False,
        "last_error": "RuntimeError: embedding gateway unavailable",
        "finished_at": "2026-11-20T00:00:00+00:00",
    }

    resp = client.get("/brain/knowledge/qa/sync-status", params={"project_id": "default"})
    assert resp.status_code == 200
    assert resp.json() == {"categories": {"cat_faq": "failed"}}
    assert scheduled == []


def test_self_heals_after_restart_by_scheduling_reindex_once(env):
    workspace, client, scheduled = env
    rel_a = "knowledge/qa/a.md"
    rel_b = "knowledge/qa/b.md"
    doc_a = _write_doc(workspace, rel_a, "## QA\n\nAA\n")
    doc_b = _write_doc(workspace, rel_b, "## QB\n\nAB\n")
    _mark_indexed(workspace, rel_a, rel_b)
    qa_nodes.create_node("cat_a", "分類 A", qa_entries=[{"question": "QA", "source_path": rel_a}])
    qa_nodes.create_node("cat_b", "分類 B", qa_entries=[{"question": "QB", "source_path": rel_b}])

    # 模擬剛重啟（記憶體 _reindex_state 是空的），但檔案已改動且不在索引裡。
    doc_a.write_text("## QA\n\nNew AA\n", encoding="utf-8")
    doc_b.write_text("## QB\n\nNew AB\n", encoding="utf-8")
    knowledge_routes._reindex_state.clear()

    resp = client.get("/brain/knowledge/qa/sync-status", params={"project_id": "default"})
    assert resp.status_code == 200
    assert resp.json() == {"categories": {"cat_a": "updating", "cat_b": "updating"}}
    # 即使多個分類都有過期文件，同一次請求也只補排一次 schedule_reindex。
    assert scheduled == ["default"]


def test_menu_only_and_disabled_documents_are_synced(env):
    workspace, client, scheduled = env
    disabled_rel = "knowledge/qa/disabled.md"
    _write_doc(workspace, disabled_rel, "## QDisabled\n\nA\n", enabled=False)
    # 停用文件故意不寫進 index_state，且設 last_error，確認不影響分類狀態。
    knowledge_routes._reindex_state["default"] = {
        "task": None,
        "dirty": False,
        "running": False,
        "last_error": "RuntimeError: boom",
        "finished_at": "2026-11-20T00:00:00+00:00",
    }

    qa_nodes.create_node(
        "cat_menu",
        "選單專用",
        qa_entries=[{"question": "只在選單上的題目", "source_path": ""}],
    )
    qa_nodes.create_node(
        "cat_disabled",
        "停用來源",
        qa_entries=[{"question": "QDisabled", "source_path": disabled_rel}],
    )
    qa_nodes.create_node("cat_empty", "空分類", qa_entries=[])

    resp = client.get("/brain/knowledge/qa/sync-status", params={"project_id": "default"})
    assert resp.status_code == 200
    assert resp.json() == {
        "categories": {
            "cat_menu": "synced",
            "cat_disabled": "synced",
            "cat_empty": "synced",
        }
    }
    assert scheduled == []


def test_direct_entries_only_and_shared_file_fingerprinted_once(env, monkeypatch):
    workspace, client, _ = env
    shared_rel = "knowledge/qa/shared.md"
    _write_doc(workspace, shared_rel, "## QShared\n\nA\n")
    _mark_indexed(workspace, shared_rel)

    stale_rel = "knowledge/qa/child_only.md"
    _write_doc(workspace, stale_rel, "## QChild\n\nA\n")

    qa_nodes.create_node(
        "parent",
        "上層",
        qa_entries=[{"question": "QShared", "source_path": shared_rel}],
    )
    qa_nodes.create_node(
        "sibling",
        "同層共用",
        qa_entries=[{"question": "QShared", "source_path": shared_rel}],
    )
    qa_nodes.create_node(
        "child",
        "子分類",
        parent_ids=["parent"],
        qa_entries=[{"question": "QChild", "source_path": stale_rel}],
    )

    knowledge_routes._reindex_state["default"] = {
        "task": None,
        "dirty": False,
        "running": False,
        "last_error": "RuntimeError: failed",
        "finished_at": "2026-11-20T00:00:00+00:00",
    }

    fp_calls: list[str] = []
    real_fp = qa_sync_status.fingerprint_document

    def counting_fp(path: Path) -> str:
        fp_calls.append(path.relative_to(workspace).as_posix())
        return real_fp(path)

    monkeypatch.setattr(qa_sync_status, "fingerprint_document", counting_fp)

    resp = client.get("/brain/knowledge/qa/sync-status", params={"project_id": "default"})
    assert resp.status_code == 200
    # 上層分類只看直接掛載的題目，不往下合併子分類的 failed。
    assert resp.json() == {
        "categories": {
            "parent": "synced",
            "sibling": "synced",
            "child": "failed",
        }
    }
    # shared.md 被兩個分類引用，但指紋只算一次。
    assert fp_calls.count(shared_rel) == 1


def test_reindex_worker_records_last_error_running_and_clears_after_success(monkeypatch):
    calls: list[str] = []
    _setup_worker(monkeypatch, calls)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        loop = asyncio.get_running_loop()

        def failing_rebuild(project_id: str):
            loop.call_soon_threadsafe(started.set)
            while not release.is_set():
                pass
            calls.append(f"fail:{project_id}")
            raise RuntimeError("embedding gateway down")

        monkeypatch.setattr(knowledge_routes, "rebuild_knowledge_index", failing_rebuild)
        knowledge_routes.schedule_reindex("p1")
        assert knowledge_routes.reindex_status("p1") == {
            "pending": True,
            "running": False,
            "last_error": None,
        }

        await started.wait()
        assert knowledge_routes.reindex_status("p1") == {
            "pending": True,
            "running": True,
            "last_error": None,
        }
        release.set()
        await knowledge_routes._reindex_state["p1"]["task"]

        failed_status = knowledge_routes.reindex_status("p1")
        assert failed_status["pending"] is False
        assert failed_status["running"] is False
        assert failed_status["last_error"] is not None
        assert "embedding gateway down" in failed_status["last_error"]
        assert knowledge_routes._reindex_state["p1"]["finished_at"] is not None

        # 下一次成功重建後清掉 last_error。
        def ok_rebuild(project_id: str):
            calls.append(f"ok:{project_id}")
            return {"status": "ok"}

        monkeypatch.setattr(knowledge_routes, "rebuild_knowledge_index", ok_rebuild)
        knowledge_routes.schedule_reindex("p1")
        await knowledge_routes._reindex_state["p1"]["task"]

        assert knowledge_routes.reindex_status("p1") == {
            "pending": False,
            "running": False,
            "last_error": None,
        }
        assert knowledge_routes._reindex_state["p1"]["finished_at"] is not None

    asyncio.run(scenario())
    assert calls == ["fail:p1", "ok:p1"]


def test_vendor_cannot_see_hidden_source_category_failure(env):
    """廠商請求依 _vendor_node 規則過濾隱藏來源：只含 knowledge/.hidden/ 題目的分類
    在過濾後沒有可見文件，回傳 synced（既不洩漏 failed，也不讓廠商反推隱藏題目存在，
    亦不因隱藏文件觸發補排重建）。
    """
    workspace, client, scheduled = env
    hidden_rel = "knowledge/.hidden/secret.md"
    visible_ok_rel = "knowledge/qa/public_ok.md"
    visible_stale_rel = "knowledge/qa/public_stale.md"

    _write_doc(workspace, hidden_rel, "## Secret\n\nTop secret\n")
    _write_doc(workspace, visible_ok_rel, "## Public OK\n\nAnswer\n")
    _write_doc(workspace, visible_stale_rel, "## Public Stale\n\nAnswer\n")
    _mark_indexed(workspace, visible_ok_rel)

    qa_nodes.create_node(
        "cat_hidden_only",
        "內部專用",
        qa_entries=[{"question": "Secret", "source_path": hidden_rel}],
    )
    qa_nodes.create_node(
        "cat_mixed",
        "混合分類",
        qa_entries=[
            {"question": "Public OK", "source_path": visible_ok_rel},
            {"question": "Secret", "source_path": hidden_rel},
        ],
    )
    qa_nodes.create_node(
        "cat_visible_failed",
        "公開待更新",
        qa_entries=[{"question": "Public Stale", "source_path": visible_stale_rel}],
    )

    knowledge_routes._reindex_state["default"] = {
        "task": None,
        "dirty": False,
        "running": False,
        "last_error": "RuntimeError: index failure",
        "finished_at": "2026-11-20T00:00:00+00:00",
    }

    # 內部帳號看得到隱藏來源的失敗狀態。
    internal_resp = client.get("/brain/knowledge/qa/sync-status", params={"project_id": "default"})
    assert internal_resp.status_code == 200
    assert internal_resp.json() == {
        "categories": {
            "cat_hidden_only": "failed",
            "cat_mixed": "failed",
            "cat_visible_failed": "failed",
        }
    }

    # 廠商帳號：只含隱藏來源的分類與混合分類（可見檔已同步）皆回 synced，公開過期分類仍為 failed。
    vendor_resp = client.get(
        "/brain/knowledge/qa/sync-status",
        params={"project_id": "default"},
        headers={"X-OpenVMan-Vendor": "1"},
    )
    assert vendor_resp.status_code == 200
    assert vendor_resp.json() == {
        "categories": {
            "cat_hidden_only": "synced",
            "cat_mixed": "synced",
            "cat_visible_failed": "failed",
        }
    }

    # 重啟場景（無 error／無 pending）：若只有隱藏來源過期，廠商查詢也不觸發 schedule_reindex。
    _mark_indexed(workspace, visible_ok_rel, visible_stale_rel)
    knowledge_routes._reindex_state.clear()
    vendor_restart_resp = client.get(
        "/brain/knowledge/qa/sync-status",
        params={"project_id": "default"},
        headers={"X-OpenVMan-Vendor": "1"},
    )
    assert vendor_restart_resp.status_code == 200
    assert vendor_restart_resp.json() == {
        "categories": {
            "cat_hidden_only": "synced",
            "cat_mixed": "synced",
            "cat_visible_failed": "synced",
        }
    }
    assert scheduled == []


def test_non_indexable_documents_ignored_and_running_retry_overrides_last_error(env):
    workspace, client, scheduled = env
    raw_rel = "raw/draft.md"
    _write_doc(workspace, raw_rel, "## Draft\n\nNot indexed\n")
    stale_rel = "knowledge/qa/retry.md"
    _write_doc(workspace, stale_rel, "## Retry\n\nContent\n")

    qa_nodes.create_node(
        "cat_non_indexable",
        "不可索引",
        qa_entries=[
            {"question": "Draft", "source_path": raw_rel},
            {"question": "Core", "source_path": "SOUL.md"},
        ],
    )
    qa_nodes.create_node(
        "cat_retrying",
        "重試中",
        qa_entries=[{"question": "Retry", "source_path": stale_rel}],
    )

    # 上一次失敗留下 last_error，但新一輪重建正在執行（running=True）：應顯示 updating，不是 failed。
    knowledge_routes._reindex_state["default"] = {
        "task": None,
        "dirty": False,
        "running": True,
        "last_error": "RuntimeError: previous error",
        "finished_at": "2026-11-20T00:00:00+00:00",
    }

    resp = client.get("/brain/knowledge/qa/sync-status", params={"project_id": "default"})
    assert resp.status_code == 200
    assert resp.json() == {
        "categories": {
            "cat_non_indexable": "synced",
            "cat_retrying": "updating",
        }
    }
    assert scheduled == []
