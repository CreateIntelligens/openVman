# Brain Roadmap — 從本地腦控台到 Agent Runtime

> **狀態（2026-05）：原 Roadmap 規劃的 Phase 1–10 已全部實作完成。**
> 此文件保留作為架構演進紀錄。新需求請在 `openspec/changes/` 開 change，不要再回填這份清單。

## 現況定位

Brain 目前是一個**可用的本地 AI 對話系統**，具備：

| 層級 | 已完成 |
|------|--------|
| 內容層 | SOUL / AGENTS / TOOLS / MEMORY 核心文件、衛教知識庫、每日對話歸檔、自動 learnings |
| 檢索層 | LanceDB + bge-m3 embedding、knowledge + memories 雙表、QA/CSV/code/freeform chunking、**增量索引（fingerprint 比對，只重建變更 chunk）** |
| 生成層 | Gemini LLM (OpenAI-compatible)、prompt builder、**system prompt 壓縮 + 對話摘要**、sync + SSE 串流 |
| Agent | **Tool loop（think → call tool → observe）、tool registry / executor、builtin knowledge/memory tools、skills 支援** |
| 韌性 | **多 key pool 輪詢 + 冷卻、fallback chain（model 降級 + retry）、provider router** |
| Session | **SQLite-backed session store（跨重啟持久化）、短期對話保留、TTL 自動清除** |
| 記憶治理 | **importance scoring、去重 / 壓縮 / 摘要、dreaming（recall tracker）、auto-recall** |
| 多通路 | **統一訊息信封（trace_id / channel / persona）、多 persona（persona-aware retrieval、per-project workspace）、對外 iframe embed channel** |
| 安全 | **input guardrails（rate limit、content filter、角色一致性）、privacy filter / egress audit** |
| 觀測 | **structured logging、Prometheus / Grafana、routing observability** |
| 部署 | Docker Compose（api / web / nginx）、GPU embedding、volume 掛載熱重載 |

---

## 演進紀錄 — 原 10 項缺口的落地情況

| # | 原缺口 | 狀態 | 落地位置 |
|---|------|------|----------|
| 1 | Tool Loop | ✅ 已完成 | `core/agent_loop.py`、`tools/tool_registry.py`、`tools/tool_executor.py`、`routes/tools.py`；archive: `2026-03-18-brain-skills-support` |
| 2 | Provider Fallback | ✅ 已完成 | `core/provider_router.py`、`core/key_pool.py`、`core/fallback_chain.py`；archive: `2026-03-18-brain-llm-failover` |
| 3 | Session 持久化 | ✅ 已完成 | `memory/session_store.py`、`tests/session/test_session_store.py` |
| 4 | Memory 治理 | ✅ 已完成 | `memory/memory_governance.py`、`memory/importance.py`、`memory/dreaming/` |
| 5 | Message 標準化 | ✅ 已完成 | `protocol/message_envelope.py`、`protocol/schemas.py`、`tests/services/test_message_envelope.py` |
| 6 | 增量索引 | ✅ 已完成 | `knowledge/indexer.py` → `rebuild_knowledge_index()`（SHA256 fingerprint + index state，回傳 `reused_chunks` / `removed_documents`） |
| 7 | Observability | ✅ 已完成 | `safety/observability.py`、`tests/services/test_routing_observability.py`；archive: `2026-04-29-prometheus-grafana-observability` |
| 8 | Input Guardrails | ✅ 已完成 | `safety/guardrails.py`、`config.py`（rate limit / content filter） |
| 9 | Prompt 壓縮 | ✅ 已完成 | `core/pipeline.py`（head+tail 截斷）、`core/prompt_builder.py` → `summarize_message_history` |
| 10 | 多 Persona | ✅ 已完成 | `personas/personas.py`、`routes/personas.py`、persona-aware retrieval（`tools/builtin/*`、`knowledge/indexer.py`） |

相關 archive changes：`2026-03-18-brain-rag-v2`、`2026-03-18-backend-gateway`、`2026-04-29-privacy-filter-egress` 等（見 `openspec/changes/archive/`）。

---
