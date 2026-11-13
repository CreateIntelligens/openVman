"""Create disposable fixtures inside new Compose volumes, then launch the service."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT = "synthetic-worker-split"
PASSWORD = "Synthetic-Worker-Only-2026"


def seed_brain():
    from config import get_settings

    cfg = get_settings()
    assert not any((
        cfg.turn_decisions_enabled, cfg.jev_language_enabled,
        cfg.jev_memory_gate_enabled, cfg.auto_recall_use_jev_filter,
        cfg.auto_recall_use_llm_summarizer, cfg.privacy_filter_enabled,
    )), "isolated load must not call external decisions or recall summaries"
    from infra.db import ensure_tables
    from knowledge.indexer import rebuild_knowledge_index
    from knowledge.workspace import ensure_workspace_scaffold

    root = ensure_workspace_scaffold(PROJECT)
    documents = {
        "services.md": "服務中心提供預約諮詢與申辦協助。週末服務必須提前預約，請攜帶預約確認單。",
        "hours.md": "服務中心平日上午九點至下午五點提供諮詢。週六預約諮詢服務為上午十點至下午三點。",
        "location.md": "虛構服務中心位於合成測試大樓一樓。預約諮詢與服務申請都在同一個櫃臺辦理。",
    }
    knowledge = root / "knowledge" / "notes"
    knowledge.mkdir(parents=True, exist_ok=True)
    for name, content in documents.items():
        (knowledge / name).write_text(content, encoding="utf-8")
    ensure_tables(PROJECT)
    result = rebuild_knowledge_index(PROJECT)
    print({"seeded_project": PROJECT, "index": result}, flush=True)


def seed_backend():
    from app.auth.models import ROOT_USERNAME, ResourceType, ResourceVisibility
    from app.auth.passwords import hash_password
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    account = runtime.users.get_by_username(ROOT_USERNAME)
    if account is None:
        account = runtime.users.create_root(username=ROOT_USERNAME, password_hash=hash_password(PASSWORD))
    existing = runtime.resources.get(ResourceType.PROJECT, PROJECT)
    if existing is None:
        runtime.resources.register(
            resource_type=ResourceType.PROJECT,
            resource_id=PROJECT,
            visibility=ResourceVisibility.PRIVATE,
            owner_user_id=account.id,
            metadata={"label": "Synthetic worker acceptance"},
        )
    elif existing.visibility is not ResourceVisibility.PRIVATE or existing.owner_user_id != account.id:
        raise RuntimeError("synthetic project registration has unexpected ownership")
    # Personas are project-scoped Brain records, not a Backend ResourceType.
    print({"seeded_synthetic_account": ROOT_USERNAME, "registered_project": PROJECT}, flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "brain":
        seed_brain()
        os.execv(sys.executable, [sys.executable, "/app/main.py"])
    elif sys.argv[1] == "backend":
        seed_backend()
        Path("/app/logs").mkdir(parents=True, exist_ok=True)
        # 跟 backend/docker/start-backend-container.sh 一樣：多 process 時準備共用的監控目錄。
        workers = os.environ.get("BACKEND_WORKERS", "1")
        if int(workers) > 1:
            import shutil

            for name, path in (("BACKEND_METRICS_DIR", "/tmp/vman-metrics"), ("PROMETHEUS_MULTIPROC_DIR", "/tmp/vman-prometheus")):
                shutil.rmtree(path, ignore_errors=True)
                os.makedirs(path)
                os.environ[name] = path
        os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200", "--workers", workers])
    else:
        raise SystemExit("expected brain or backend")
