"""Brain lifecycle, background warmup and startup degradation."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from config import get_settings
from infra.db import ensure_tables, get_db
from infra.project_admin import list_projects
from infra.shared_budgets import shared_request_budget
from infra.usage_ledger import flush_usage_events
from knowledge.product_catalog import load_product_catalogs
from knowledge.workspace import ensure_workspace_scaffold
from memory.embedder import get_embedder
from memory.memory_governance import maybe_run_memory_maintenance
from safety.observability import get_metrics_store
from warmup_state import mark_warmup_done

logger = logging.getLogger("brain")

# 等 Backend 重啟最多約 10 秒；之後各專案的預熱只試一次，Backend 真的掛了不拖慢啟動。
_AUDIO_WARMUP_ATTEMPTS = 6
_AUDIO_WARMUP_RETRY_SECONDS = 2.0


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


def _warmup_audio_language(project_id: str = "default", attempts: int = 1) -> None:
    """Import google-genai and warm the selected project's resolved client.

    台語判斷只能等 2.5 秒；部署重啟後第一句要付載入套件、建 client、跟 Gemini
    建連線，實測 2.5 秒（之後 1.2 秒），第一個講台語的人會被當成講華語。
    models.get 不花 token。

    *attempts* > 1 時失敗會隔幾秒重試：watchtower 換版會同時重啟 Backend，
    剛啟動時拿不到金鑰（ConnectError），等 Backend 起來就好了。
    """
    cfg = get_settings()
    from core.gemini_credentials import resolve_gemini_credential
    from memory.language_detect import _audio_language_client

    for attempt in range(1, attempts + 1):
        try:
            credential = resolve_gemini_credential(project_id)
            if not credential.api_key:
                return
            _audio_language_client(credential.api_key).models.get(
                model=cfg.live_audio_language_id_model,
            )
            return
        except Exception as exc:  # noqa: BLE001 - 預熱失敗只是第一句慢，不擋啟動
            if attempt < attempts:
                time.sleep(_AUDIO_WARMUP_RETRY_SECONDS)
                continue
            logger.warning("台語判斷預熱失敗（不影響啟動）: %s", type(exc).__name__)


def _warmup_llm_modules() -> None:
    """先載入 LLM 相關套件：google-genai 第一次 import 要一到兩秒 CPU。

    原本在第一題組 fallback chain 時才載入，每個 worker 都在第一批題目上付這筆錢；
    換版後馬上同時進來 100 題時，所有 worker 一起 import，回覆會整批慢好幾秒。
    """
    import core.models_config  # noqa: F401  （連帶載入 google.genai）
    import openai.resources.chat  # noqa: F401


def _warmup_product_catalogs(project_id: str) -> None:
    """先解析型錄：第一題才讀上百份產品筆記，會跟同時進來的題目搶 CPU。"""
    try:
        load_product_catalogs(project_id)
    except Exception as exc:  # 型錄壞掉時第一題照樣會回報錯在哪，預熱不擋啟動
        logger.warning("型錄預熱失敗 project=%s: %s", project_id, type(exc).__name__)


def _warmup_model_settings(project_ids: list[str]) -> None:
    """先向 Backend 取一次模型與決策設定，第一批題目就不用各自去拿。"""
    from core.decision_router import _provider_configuration
    from core.fallback_chain import _admin_chat
    from core.gemini_credentials import resolve_gemini_credential

    loaders = [
        ("decision", lambda: _provider_configuration(timeout=3.0)),
        ("chat_llm", _admin_chat),
        *((f"gemini_credential:{pid}", lambda pid=pid: resolve_gemini_credential(pid)) for pid in project_ids),
    ]
    for name, load in loaders:
        try:
            load()
        except Exception as exc:  # 取不到時第一題照常自己取，預熱不擋啟動
            logger.warning("模型設定預熱失敗 %s: %s", name, type(exc).__name__)


async def warmup_resources(role: str | None = None) -> None:
    """背景預熱 remote embedding 與資料路徑。"""
    role = role or get_settings().brain_role
    logger.info("背景預熱開始...")
    # 最先做：部署後第一句台語可能在其他預熱跑完前就到。
    await asyncio.to_thread(_warmup_audio_language, "default", _AUDIO_WARMUP_ATTEMPTS)
    try:
        await asyncio.to_thread(_warmup_llm_modules)
        project_ids = _warmup_project_ids()
        await asyncio.to_thread(_warmup_model_settings, project_ids)
        await asyncio.to_thread(get_embedder)
        for project_id in project_ids:
            if project_id != "default":
                await asyncio.to_thread(_warmup_audio_language, project_id)
            if role == "admin":
                ensure_workspace_scaffold(project_id)
                await asyncio.to_thread(ensure_tables, project_id)
            # _warmup_retrieval_path 內部已逐表吞掉預熱失敗、不會 raise。
            await asyncio.to_thread(_warmup_retrieval_path, project_id)
            await asyncio.to_thread(_warmup_product_catalogs, project_id)
        if role == "admin":
            await asyncio.to_thread(maybe_run_memory_maintenance, True, "default")
    except Exception as exc:
        logger.warning(
            "背景預熱未完整執行（不阻斷服務 readiness）: %s",
            type(exc).__name__,
        )
    finally:
        mark_warmup_done()
        logger.info("背景預熱完成")


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
    cfg = get_settings()
    role = getattr(app.state, "brain_role", cfg.brain_role)
    if role == "chat" and cfg.brain_workers > 1:
        if not os.environ.get("BRAIN_METRICS_RUN_ID"):
            raise RuntimeError("multi-worker chat requires BRAIN_METRICS_RUN_ID")
        if not cfg.brain_coordination_dir:
            raise RuntimeError("multi-worker chat requires BRAIN_COORDINATION_DIR")
    # Validate shared paths at startup, before the first user's request.
    if cfg.brain_coordination_dir:
        shared_request_budget(cfg.brain_coordination_dir)
    get_metrics_store()
    if cfg.brain_thread_pool_size:
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(max_workers=cfg.brain_thread_pool_size)
        )

    if role == "admin":
        ensure_workspace_scaffold("default")
        get_db("default")
        from scripts.migrate_to_projects import run_migration

        await asyncio.to_thread(run_migration)

    app.state.warmup_task = asyncio.create_task(warmup_resources(role))
    if role == "admin":
        if cfg.dreaming_enabled:
            from memory.dreaming.scheduler import start_dreaming_scheduler

            await start_dreaming_scheduler(app)
        from memory.maintenance_scheduler import start_maintenance_scheduler
        from memory.session_backup import start_backup_scheduler

        app.state.session_backup_task = start_backup_scheduler()
        app.state.memory_maintenance_task = start_maintenance_scheduler()

    logger.info("大腦層就緒（role=%s）", role)
    try:
        yield
    finally:
        await asyncio.gather(*(
            cancel_task(getattr(app.state, name, None))
            for name in (
                "session_backup_task", "dreaming_task", "warmup_task",
                "memory_maintenance_task",
            )
        ))
        # 用量是背景批次寫入；正常停機／重新部署前把排隊中的寫完。uvicorn 收到
        # SIGTERM 時會在 serve() 結束後用預設處理再送一次訊號，process 直接結束、
        # 不會跑 atexit，所以這裡是停機時唯一可靠的寫入點。
        if not await asyncio.to_thread(flush_usage_events):
            logger.error("usage ledger: pending events not written before shutdown")
