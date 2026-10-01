"""Brain lifecycle, background warmup and startup degradation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from config import get_settings
from infra.db import ensure_tables, get_db
from infra.project_admin import list_projects
from knowledge.workspace import ensure_workspace_scaffold
from memory.embedder import get_embedder
from memory.memory_governance import maybe_run_memory_maintenance
from warmup_state import mark_warmup_done

logger = logging.getLogger("brain")


def _warmup_project_ids() -> list[str]:
    project_ids = ["default"]
    seen = {"default"}
    try:
        projects = list_projects()
    except Exception as exc:
        logger.warning("專案預熱清單讀取失敗（僅預熱 default）: %s", exc)
        return project_ids

    for project in projects:
        project_id = str(project.get("project_id", "")).strip()
        if not project_id or project_id in seen:
            continue
        document_count = int(project.get("document_count") or 0)
        if not project.get("has_lancedb") and document_count <= 0:
            continue
        project_ids.append(project_id)
        seen.add(project_id)
    return project_ids


_WARMUP_TABLES = ("knowledge", "memories")


def _warmup_retrieval_path(project_id: str = "default") -> None:
    """真正跑一次 remote encode + search，預熱 gateway 與 LanceDB 查詢路徑。

    僅建立 HTTP client/table 物件不會驗證 gateway inference 或 LanceDB 查詢。
    這裡實際呼叫一次檢索，把完整 remote hot path 熱起來，避免第一個使用者
    請求承擔連線與查詢冷啟成本。

    knowledge 與 memories 各自有獨立的 LanceDB 查詢路徑與 FTS 索引；search_memory
    走的是 memories 表，若只暖 knowledge，第一個「我是誰」這類記憶查詢仍會冷啟。
    因此兩個表都要暖。
    """
    from memory.embedder import encode_query_with_fallback
    from memory.retrieval import search_records

    for table_name in _WARMUP_TABLES:
        try:
            route = encode_query_with_fallback(
                "warmup", project_id=project_id, table_names=(table_name,)
            )
            search_records(
                table_name=table_name,
                query_vector=route.vector,
                top_k=1,
                query_text="warmup",
                query_type="hybrid",
                project_id=project_id,
                embedding_version=route.version,
            )
        except Exception as exc:  # 單一表預熱失敗不應阻擋其他表
            logger.warning(
                "檢索路徑預熱失敗（project=%s table=%s，不影響啟動）: %s",
                project_id,
                table_name,
                exc,
            )


def _warmup_audio_language() -> None:
    """Import google-genai, build the shared client and open its connection.

    台語判斷只能等 2.5 秒；部署重啟後第一句要付載入套件、建 client、跟 Gemini
    建連線，實測 2.5 秒（之後 1.2 秒），第一個講台語的人會被當成講華語。
    models.get 不花 token。
    """
    cfg = get_settings()
    if not cfg.gemini_api_key:
        return
    from memory.language_detect import _audio_language_client

    try:
        _audio_language_client(cfg.gemini_api_key).models.get(
            model=cfg.live_audio_language_id_model,
        )
    except Exception as exc:  # noqa: BLE001 - 預熱失敗只是第一句慢，不擋啟動
        logger.warning("台語判斷預熱失敗（不影響啟動）: %s", type(exc).__name__)


async def warmup_resources() -> None:
    """背景預熱 remote embedding 與資料路徑。"""
    logger.info("背景預熱開始...")
    # 最先做：部署後第一句台語可能在其他預熱跑完前就到。
    await asyncio.to_thread(_warmup_audio_language)
    try:
        project_ids = _warmup_project_ids()
        await asyncio.to_thread(get_embedder)
        for project_id in project_ids:
            ensure_workspace_scaffold(project_id)
            await asyncio.to_thread(ensure_tables, project_id)
            # _warmup_retrieval_path 內部已逐表吞掉預熱失敗、不會 raise。
            await asyncio.to_thread(_warmup_retrieval_path, project_id)
        await asyncio.to_thread(maybe_run_memory_maintenance, True, "default")
    except Exception as exc:
        logger.warning(
            "背景預熱未完整執行（不阻斷服務 readiness）: %s",
            type(exc).__name__,
        )
    finally:
        mark_warmup_done()
        logger.info("背景預熱完成")


async def load_privacy_filter_if_enabled() -> None:
    """Load Privacy Filter model when enabled, degrading safely on failure."""
    if not get_settings().privacy_filter_enabled:
        return

    from privacy.model import load_privacy_filter_model

    try:
        await asyncio.to_thread(load_privacy_filter_model)
    except Exception as exc:
        logger.warning("Privacy Filter GPU load failed; retrying on CPU: %s", exc)
        from privacy.model import disable_privacy_filter, load_privacy_filter_model_cpu
        try:
            await asyncio.to_thread(load_privacy_filter_model_cpu)
        except Exception as cpu_exc:
            logger.warning("Privacy Filter CPU load also failed; disabling filter: %s", cpu_exc)
            disable_privacy_filter(f"model_load_failed: {cpu_exc}")



async def cancel_task(task: asyncio.Task[None] | None) -> None:
    """在 shutdown 時 safe 取消背景任務。"""
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """啟動時先讓服務可用，再背景預熱重資源。"""
    logger.info("初始化大腦層資源...")
    # 確保預設工作區與資料庫連線
    ensure_workspace_scaffold("default")
    get_db("default")

    # 執行資料遷移
    from scripts.migrate_to_projects import run_migration
    await asyncio.to_thread(run_migration)
    await load_privacy_filter_if_enabled()

    # 背景預熱 remote embedding 與資料路徑
    app.state.warmup_task = asyncio.create_task(warmup_resources())

    # Start dreaming scheduler (opt-in)
    if get_settings().dreaming_enabled:
        from memory.dreaming.scheduler import start_dreaming_scheduler
        await start_dreaming_scheduler(app)

    from memory.session_backup import start_backup_scheduler
    app.state.session_backup_task = start_backup_scheduler()

    logger.info("大腦層就緒")
    yield
    await asyncio.gather(
        cancel_task(getattr(app.state, "session_backup_task", None)),
        cancel_task(getattr(app.state, "dreaming_task", None)),
        cancel_task(getattr(app.state, "warmup_task", None)),
    )
