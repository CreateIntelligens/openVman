# TASK-21: Daily Memory Writeback and Re-index Hooks

> Issue: #30 — Daily memory writeback and re-index hooks
> Epic: #7
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

把有用的對話摘要穩定寫回 daily memory file，並掛上重建 `memories` 表的 hook，同時做基本重複控制。

| 需求 | 說明 |
|------|------|
| summary writeback flow | 對話摘要可寫回 memory store |
| daily memory file output | daily file 格式穩定，便於後續 parse / reindex |
| re-index trigger / hook | 寫回後可重建或更新 `memories` 表 |
| duplicate-control basics | 基本去重，避免同摘要無限制重複插入 |
| scope control | 本 task 先做基本摘要與 reindex hook，不做高階反思治理 |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L243) | Spec 已要求把當日摘要寫入 `memory/YYYY-MM-DD.md` 並重建 `memories` 表 |
| [memory.py](brain/api/memory/memory.py#L84) | 目前已有 `archive_session_turn()` 將原始對話寫入 `memory/YYYY-MM-DD.md` |
| [memory_governance.py](brain/api/memory/memory_governance.py#L1) | 目前已有每日摘要生成、去重與 memories overwrite 重建的骨架 |
| [workspace.py](brain/api/knowledge/workspace.py#L15) | 目前已有 `.learnings/MEMORY_SUMMARIES.md` scaffold |

### 缺口

| 缺口 | 說明 |
|------|------|
| summary 沒寫回 daily file | 目前 summary 寫到 `.learnings/MEMORY_SUMMARIES.md`，不是 spec 要的 `memory/YYYY-MM-DD.md` |
| raw log 與 summary 沒有穩定分段 | 現有 daily file 是 raw turn archive，還沒有固定 summary section |
| re-index hook 不明確 | 目前 memory maintenance 是批次治理，不是 writeback 後的明確 hook |
| duplicate-control 粗糙 | 現有 dedupe 偏整表文字去重，未針對 daily summary writeback 做基本界線 |

---

## 開發方法

### 架構

```text
session transcript
    │
    ├─ summarize useful signals
    ├─ append stable summary block to memory/YYYY-MM-DD.md
    ├─ compute summary fingerprint
    ├─ skip if duplicate within bounded rule
    └─ trigger memories re-index hook
```

### 設計決策

1. **沿用現有 `memory_governance.py`**  
   不另開新的治理系統，直接補齊 daily file writeback 與 re-index hook。

2. **daily file 保留 raw log，但新增穩定 summary section**  
   不立刻推翻 `archive_session_turn()`，先在同一天檔案中加入可 parse 的 summary block。

3. **duplicate-control 先用 fingerprint + day + persona**  
   基本控制即可，先防止同內容無限制追加。

4. **re-index hook 先做同步或薄 job hook**  
   不先引入完整排程系統；可在 writeback 成功後直接觸發 memories rebuild 或 queue hook。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. daily summary format | 定義 `memory/YYYY-MM-DD.md` 的 summary 區塊格式 | `brain/api/memory/memory_governance.py` |
| 2. writeback flow | 實作寫回 summary block 與 fingerprint 檢查 | `brain/api/memory/memory_governance.py` |
| 3. duplicate-control | 加入基本去重規則 | `brain/api/memory/memory_governance.py` |
| 4. re-index hook | 寫回後觸發 `memories` 表重建或 job hook | `brain/api/memory/memory_governance.py` |
| 5. 現有 call site 整合 | chat finalize / maintenance flow 對齊新 hook | `brain/api/core/chat_service.py` |
| 6. 測試 | daily file format、reindex、duplicate-control 測試 | `brain/api/tests/test_memory_governance.py` |

---

## 詳細設計

### 1. Daily file format

`memory/default/2026-03-15.md`

```md
# 2026-03-15 對話日誌

## 10:32:15 | session abc

### User
你好

### Assistant
您好，有什麼需要協助？

# 記憶摘要

## 2026-03-15T10:40:00+08:00 | session abc

- persona_id: default
- fingerprint: 2d9b7f...
- source_turns: 8

### Summary
- 使用者詢問糖尿病飲食控制
- 偏好簡短、直接回覆
```

規則：
- raw transcript 保持現有格式
- summary 區塊固定從 `# 記憶摘要` 開始
- parser 只吃 summary 區塊，不重新解析 raw turns

### 2. duplicate-control

首版規則：
- 以 `(persona_id, day, fingerprint)` 當唯一鍵
- 若當日檔案已有同 fingerprint summary block，直接跳過
- memories table rebuild 時，同 fingerprint 的 daily summary 只保留一筆

### 3. Re-index hook

首版選項：

1. `write_summary_and_reindex(...)`
   - 寫回 summary block
   - 立刻呼叫 `run_memory_maintenance()` 或 summary-specific rebuild

2. `write_summary_and_mark_dirty(...)`
   - 寫回 summary block
   - 設 dirty flag，交給下一次 maintenance 處理

建議首版先做第 1 種，簡單直接。

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_daily_summary_written_to_stable_memory_file_format` | summary block 會寫進 `memory/YYYY-MM-DD.md` 且格式穩定 |
| `test_memory_summary_can_be_reindexed_into_memories_table` | writeback 後可成功 rebuild `memories` 表 |
| `test_duplicate_summary_is_bounded_by_fingerprint` | 同摘要不會無限制重複寫入 |
| `test_raw_transcript_and_summary_sections_coexist` | 不會破壞既有 transcript archive |
| `test_reindex_hook_runs_after_successful_writeback` | writeback 成功後會進行 re-index hook |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| memory governance 測試 | `python3 -m pytest brain/api/tests/test_memory_governance.py -v` | writeback + duplicate-control + reindex |
| 全 brain 測試 | `python3 -m pytest brain/api/tests/ -v` | 不打壞現有 memory flow |

### 手動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| daily file | 觸發一輪 summary writeback | `memory/YYYY-MM-DD.md` 出現穩定 summary block |
| re-index hook | writeback 後查 `memories` 表 | 新 summary 可被檢索 |
| duplicate-control | 重複觸發同摘要 | 寫入次數受限 |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| memory summary 可成功寫回並重建索引 | writeback + reindex 測試 |
| daily file 格式穩定 | stable format 測試與人工檢查 |
| 重複寫入有基本控制 | fingerprint 去重測試 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/memory/memory_governance.py` | 修改 | daily summary writeback、duplicate-control、re-index hook |
| `brain/api/core/chat_service.py` | 修改 | finalize / maintenance flow 對齊 writeback hook |
| `brain/api/tests/test_memory_governance.py` | 新增 | daily file / reindex / duplicate-control 測試 |
| `docs/plans/TASK-21-daily-memory-writeback-and-re-index-hooks.md` | 新增 | 計畫書（本文件） |

