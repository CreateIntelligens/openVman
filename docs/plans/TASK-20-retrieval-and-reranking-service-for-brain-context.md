# TASK-20: Retrieval and Reranking Service for Brain Context

> Issue: #29 — Retrieval and reranking service for brain context
> Epic: #7
> Branch: `feature/brain`
> Status: **Planned**

---

## 開發需求

完成供 brain pipeline 使用的 retrieval 與 reranking 服務，能從 `knowledge` 與 `memories` 表取回相關 context，並保留排名與距離的可觀測性。

| 需求 | 說明 |
|------|------|
| query embedding | 對 query 產生 embedding |
| top-k retrieval | 從 `knowledge` / `memories` 取回 top-k 候選 |
| merge and rerank | 合併候選並做最終排序 |
| diagnostics logging | 記錄 ranking、distance、來源與 top-k 行為 |
| config-aligned top-k | 行為需受設定控制，不可寫死 |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [03_BRAIN_SPEC.md](/home/human/openVman/03_BRAIN_SPEC.md#L114) | Brain 需從 LanceDB `knowledge` / `memories` 取 Top-K context |
| [03_BRAIN_SPEC.md](/home/human/openVman/03_BRAIN_SPEC.md#L139) | Spec 已提供 knowledge + memories 檢索概念 |
| [retrieval.py](/home/human/openVman/brain/api/memory/retrieval.py#L1) | 現有模組已有 low-level LanceDB search 與 persona filter |
| [chat_service.py](/home/human/openVman/brain/api/core/chat_service.py#L95) | 現行 RAG path 直接在 `chat_service` 中做 embedding + table search |

### 缺口

| 缺口 | 說明 |
|------|------|
| 沒有統一 retrieval service | 現在 embedding、knowledge search、memory search 分散在 `chat_service` 與 `retrieval.py` |
| 沒有 merge / rerank | knowledge 與 memories 只是分開查，沒有統一 rerank 規則 |
| 沒有 retrieval diagnostics | 看不到距離、排序結果、候選裁剪過程 |
| top-k 只有單一 `rag_top_k` | 尚未細分 knowledge / memory top-k 與 rerank candidate 上限 |

---

## 開發方法

### 架構

```text
user query
    │
    ├─ encode_text(query)
    ├─ search knowledge top_k
    ├─ search memories top_k
    ├─ merge candidates
    ├─ rerank by distance + source policy
    └─ return
         ├─ knowledge_results
         ├─ memory_results
         └─ diagnostics
```

### 設計決策

1. **把 retrieval 從 `chat_service` 抽出**  
   `chat_service` 只負責 orchestrate，retrieval 細節集中到 service。

2. **保留 knowledge / memory 分欄輸出**  
   最終 prompt builder 仍可吃分開來源，但 service 內部會先做統一候選與 diagnostics。

3. **rerank 先用 deterministic policy**  
   首版不引入 cross-encoder，先依 `_distance` 與 source bias 做穩定排序。

4. **diagnostics 要可記錄候選裁剪**  
   不能只看最後 top-k，要能知道每一層候選的來源與距離。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. retrieval config | 補 knowledge/memory top-k 與 rerank 設定 | `brain/api/config.py` |
| 2. retrieval service | 建立統一 retrieval / rerank service | `brain/api/core/retrieval_service.py` |
| 3. low-level search 對齊 | 保留 `memory/retrieval.py` 做 table search helper | `brain/api/memory/retrieval.py` |
| 4. chat_service 整合 | `_retrieve_rag_context()` 改走 retrieval service | `brain/api/core/chat_service.py` |
| 5. diagnostics logging | 補 retrieval candidate / rerank log | `brain/api/core/retrieval_service.py` |
| 6. 測試 | known prompts、top-k、distance observability 測試 | `brain/api/tests/test_retrieval_service.py` |

---

## 詳細設計

### 1. Config

新增建議設定：

```env
RAG_KNOWLEDGE_TOP_K=5
RAG_MEMORY_TOP_K=3
RAG_RERANK_CANDIDATE_MULTIPLIER=4
RAG_RERANK_FINAL_TOP_K=5
RAG_MEMORY_DISTANCE_BONUS=0.02
```

### 2. Retrieval service API

```python
@dataclass
class RetrievalBundle:
    knowledge_results: list[dict[str, Any]]
    memory_results: list[dict[str, Any]]
    diagnostics: dict[str, Any]

def retrieve_context(
    *,
    query: str,
    persona_id: str,
) -> RetrievalBundle:
    ...
```

### 3. Rerank policy

首版規則：
- 先各自取候選：
  - knowledge = `knowledge_top_k * candidate_multiplier`
  - memories = `memory_top_k * candidate_multiplier`
- 合併後以 `_distance` 升序排序
- memory 可給小幅 distance bonus，避免近期對話完全被知識庫淹沒
- 最後再切回：
  - final knowledge top-k
  - final memory top-k

### 4. Diagnostics

至少記錄：

```json
{
  "query": "糖尿病常見症狀",
  "knowledge_candidates": 12,
  "memory_candidates": 8,
  "final_knowledge": 5,
  "final_memory": 3,
  "top_hits": [
    {"source": "knowledge", "distance": 0.11, "path": "hospital_education/diabetes.md"},
    {"source": "memory", "distance": 0.14, "day": "2026-03-15"}
  ]
}
```

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_known_prompt_returns_relevant_knowledge_context` | 已知測試題可取回相關 knowledge |
| `test_known_prompt_returns_relevant_memory_context` | 已知對話可取回相關 memory |
| `test_top_k_behavior_matches_config` | knowledge / memory top-k 受 config 控制 |
| `test_rerank_orders_by_distance_with_source_policy` | rerank 規則可預測 |
| `test_retrieval_diagnostics_exposes_distance_and_ranking` | diagnostics 含 distance / ranking |
| `test_chat_service_uses_retrieval_service_bundle` | chat_service 整合後仍拿到分開來源結果 |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| retrieval 測試 | `python3 -m pytest brain/api/tests/test_retrieval_service.py -v` | query -> retrieval -> rerank |
| pipeline 測試 | `python3 -m pytest brain/api/tests/test_pipeline.py -v` | chat_service 整合不壞 |
| 全 brain 測試 | `python3 -m pytest brain/api/tests/ -v` | 不打壞現有 brain flow |

### 手動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| 已知測試題 | 用固定 query 打 generate / search | 可取回相關 context |
| diagnostics | 查看 retrieval logs | 可看到距離與排序 |
| top-k 行為 | 調整 config 後重跑 | 結果數量符合設定 |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| 已知測試題能取回相關 context | retrieval 測試與手動 query 驗證 |
| ranking 與 distance 可觀測 | diagnostics 測試與 logs |
| top-k 行為符合設定 | config 驅動測試 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/core/retrieval_service.py` | 新增 | 統一 retrieval / rerank service |
| `brain/api/memory/retrieval.py` | 修改 | 保留 low-level search helper，配合 service |
| `brain/api/core/chat_service.py` | 修改 | 改走 retrieval service |
| `brain/api/config.py` | 修改 | 新增 retrieval / rerank config |
| `brain/api/tests/test_retrieval_service.py` | 新增 | retrieval / rerank / diagnostics 測試 |
| `docs/plans/TASK-20-retrieval-and-reranking-service-for-brain-context.md` | 新增 | 計畫書（本文件） |

