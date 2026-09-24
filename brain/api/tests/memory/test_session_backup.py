"""Tests for the per-language session backup (VH-389)."""

from __future__ import annotations

import json
import types
from datetime import UTC, datetime, timedelta

import pytest

from memory import session_backup
from memory.session_store import SessionStore


@pytest.fixture
def projects(tmp_path, monkeypatch):
    data_root = tmp_path / "projects"
    stores: dict[str, SessionStore] = {}
    for project_id in ("alpha", "beta"):
        (data_root / project_id).mkdir(parents=True)
        stores[project_id] = SessionStore(db_path=str(data_root / project_id / "sessions.db"))
    # 沒有 sessions.db 的專案不該被備份，也不該被建出空庫。
    (data_root / "empty").mkdir()

    settings = types.SimpleNamespace(
        session_backup_dir=str(tmp_path / "backups"), session_backup_keep=2,
    )
    monkeypatch.setattr(session_backup, "get_settings", lambda: settings)
    monkeypatch.setattr(session_backup, "get_data_root", lambda: data_root)
    monkeypatch.setattr(session_backup, "get_session_store", lambda pid: stores[pid])
    monkeypatch.setattr(
        "memory.session_store.refine_language_in_background", lambda *a, **kw: None,
    )

    stores["alpha"].append_message("zh-1", "default", "user", "地下室抽污水用哪款")
    stores["alpha"].append_message("zh-1", "default", "assistant", "推薦 HIPPO。")
    stores["alpha"].append_message("es-1", "default", "user", "¿Qué bomba me recomiendas?")
    stores["beta"].append_message("en-1", "default", "user", "Which pump do you recommend?")
    return tmp_path / "backups", settings


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_backup_splits_sessions_by_language(projects):
    root, _ = projects

    manifest = session_backup.run_backup()

    backup_dir = root / manifest["backup_id"]
    assert sorted(p.name for p in (backup_dir / "alpha").iterdir()) == ["es.jsonl", "zh.jsonl"]
    zh = _read_jsonl(backup_dir / "alpha" / "zh.jsonl")
    assert [s["session_id"] for s in zh] == ["zh-1"]
    assert [m["content"] for m in zh[0]["messages"]] == ["地下室抽污水用哪款", "推薦 HIPPO。"]
    assert _read_jsonl(backup_dir / "beta" / "en.jsonl")[0]["session_id"] == "en-1"
    assert not (backup_dir / "empty").exists()
    assert manifest["total_sessions"] == 3
    assert manifest["total_messages"] == 4
    assert session_backup.list_backups()[0]["backup_id"] == manifest["backup_id"]


def test_dry_run_counts_without_writing(projects):
    root, _ = projects

    manifest = session_backup.run_backup(dry_run=True)

    assert manifest["dry_run"] is True
    assert {p["project_id"]: p["sessions"] for p in manifest["projects"]} == {
        "alpha": {"zh": 1, "en": 0, "es": 1, "nan": 0},
        "beta": {"zh": 0, "en": 1, "es": 0, "nan": 0},
    }
    assert not root.exists()


def test_only_one_backup_runs_at_a_time(projects):
    session_backup._lock.acquire()
    try:
        with pytest.raises(session_backup.BackupInProgressError):
            session_backup.run_backup()
    finally:
        session_backup._lock.release()


@pytest.mark.parametrize("dry_run", [True, False])
def test_backup_preserves_expired_sessions(projects, dry_run):
    root, _ = projects
    store = session_backup.get_session_store("alpha")
    expired = (datetime.now(UTC) - timedelta(days=3650)).isoformat()
    with store._connect() as conn:
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (expired, "zh-1"),
        )
        conn.commit()
        before = list(conn.iterdump())

    manifest = session_backup.run_backup(dry_run=dry_run)

    with store._connect() as conn:
        assert list(conn.iterdump()) == before
    assert manifest["total_sessions"] == 3
    assert manifest["total_messages"] == 4
    if dry_run:
        assert not root.exists()
    else:
        sessions = _read_jsonl(
            root / manifest["backup_id"] / "alpha" / "zh.jsonl",
        )
        assert sessions[0]["session_id"] == "zh-1"
        assert sessions[0]["message_count"] == len(sessions[0]["messages"]) == 2
        assert [message["content"] for message in sessions[0]["messages"]] == [
            "地下室抽污水用哪款", "推薦 HIPPO。",
        ]


def test_keeps_only_the_newest_backups(projects):
    root, settings = projects
    root.mkdir()
    for name in ("20260101-000000", "20260102-000000", "20260103-000000"):
        (root / name).mkdir()
    (root / ".20260104-000000.partial").mkdir()

    removed = session_backup._prune(root)

    assert removed == ["20260101-000000"]
    assert sorted(p.name for p in root.iterdir()) == ["20260102-000000", "20260103-000000"]
