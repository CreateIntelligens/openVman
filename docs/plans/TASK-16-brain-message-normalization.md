# TASK-16: Brain Message Normalization and Enrichment Stage

> Issue: #25 — Brain message normalization and enrichment stage
> Epic: #6
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

完成 brain message pipeline 前半段：normalize 與 enrich，確保所有請求進入 brain 前都是統一格式。

| 需求 | 說明 |
|------|------|
| 標準化角色 | 將 `message_type` 正式對應 spec 定義的 5 種 role：`system \| user \| assistant \| tool \| control` |
| 豐富化 | 確保 locale / persona_id / trace_id / session_id / channel 在所有 internal stage 不遺失 |
| 內部訊息結構 | 定義 `BrainMessage` TypedDict 作為 pipeline 各 stage 的統一傳遞格式 |
| 測試覆蓋 | `build_message_envelope`、`serialize_context`、enrichment 邏輯皆有單元測試 |

---

## 現況分析

### 已完成

`message_envelope.py` 已實作：
- `RequestContext` dataclass：含 trace_id, session_id, message_type, channel, locale, persona_id, client_ip, metadata
- `build_message_envelope()`：從 legacy/structured body normalize 成 `MessageEnvelope`
- `serialize_context()`：序列化 context 為 dict
- enrichment fallback chain（trace_id 5 層、locale 從 body → header → `zh-TW`）

### 缺口

| 缺口 | 說明 |
|------|------|
| 無 `BrainMessage` 型別 | Spec 定義 `BrainMessage(TypedDict)` 含 `role` 欄位，目前不存在 |
| `message_type` 不完整 | `guardrails.py` 只允許 `user \| tool \| control`，spec 要 5 種 role |
| 零測試覆蓋 | `message_envelope.py` 完全沒有單元測試 |
| context 存活性未驗證 | locale / persona / trace 是否在 pipeline 各 stage 保留，沒有測試保證 |

---

## 開發方法

### 架構

```
HTTP Request / WebSocket Event
    │
    ▼
build_message_envelope(request, body)     ← 現有，不改動
    │
    ▼
MessageEnvelope { content, context }
    │
    ▼
normalize_to_brain_message(envelope)      ← 新增
    │
    ▼
BrainMessage { role, content, trace_id, session_id,
               persona_id, locale, channel, metadata }
    │
    ▼
prepare_generation / guardrails / ...     ← 下游 stage 消費 BrainMessage
```

### 設計決策

1. **不破壞現有 `MessageEnvelope`**：`MessageEnvelope` 仍負責 HTTP 層 normalize，新增 `BrainMessage` 作為 pipeline 內部統一格式
2. **`BrainMessage` 用 dataclass** 而非 TypedDict：與 `RequestContext` 風格一致，且有 slot 效能優勢
3. **`message_type` → `role` 映射**：在 `normalize_to_brain_message()` 中將 `message_type` 轉為 spec 定義的 role
4. **`system` / `assistant` role**：這兩個 role 不從外部請求產生，而是由 `prompt_builder.py` 等內部 stage 建構時使用

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 寫失敗測試 | build_message_envelope / serialize_context / BrainMessage 建構 / context 保留 | `brain/api/tests/test_message_envelope.py` |
| 2. 定義 BrainMessage | dataclass with role, content, trace_id, session_id, persona_id, locale, channel, metadata | `brain/api/protocol/message_envelope.py` |
| 3. 新增 normalize 函式 | `normalize_to_brain_message(envelope)` → `BrainMessage` | `brain/api/protocol/message_envelope.py` |
| 4. 新增 factory 函式 | `create_brain_message(role, content, *, context)` 供 prompt_builder 等內部 stage 使用 | `brain/api/protocol/message_envelope.py` |
| 5. 擴充 allowed roles | guardrails 的 message_type 驗證加入 `system` / `assistant` | `brain/api/safety/guardrails.py` |
| 6. 確認測試全過 | 驗證所有 enrichment 欄位在轉換後保留 | `pytest -v` |

### `BrainMessage` 設計

```python
ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool", "control"})

@dataclass(slots=True, frozen=True)
class BrainMessage:
    role: str           # system | user | assistant | tool | control
    content: str
    trace_id: str
    session_id: str | None
    persona_id: str
    locale: str
    channel: str
    metadata: dict[str, Any]
```

### `normalize_to_brain_message`

```python
def normalize_to_brain_message(envelope: MessageEnvelope) -> BrainMessage:
    ctx = envelope.context
    return BrainMessage(
        role=ctx.message_type,
        content=envelope.content,
        trace_id=ctx.trace_id,
        session_id=ctx.session_id,
        persona_id=ctx.persona_id,
        locale=ctx.locale,
        channel=ctx.channel,
        metadata=dict(ctx.metadata),   # defensive copy
    )
```

### `create_brain_message`

```python
def create_brain_message(
    role: str,
    content: str,
    *,
    context: RequestContext,
) -> BrainMessage:
    """Create a BrainMessage for internal stages (system prompt, assistant reply, etc.)."""
    return BrainMessage(
        role=role,
        content=content,
        trace_id=context.trace_id,
        session_id=context.session_id,
        persona_id=context.persona_id,
        locale=context.locale,
        channel=context.channel,
        metadata=dict(context.metadata),
    )
```

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| 單元測試 | `python3 -m pytest brain/api/tests/test_message_envelope.py -v` | normalize / enrich / context 保留 |
| 既有測試不壞 | `python3 -m pytest brain/api/tests/ -v` | 所有測試仍 pass |

### 測試案例規劃

| 測試 | 驗證內容 |
|------|---------|
| `test_build_envelope_from_flat_body` | legacy flat body 正確 normalize |
| `test_build_envelope_from_structured_message` | nested message dict 正確解析 |
| `test_build_envelope_enriches_trace_id_from_header` | X-Trace-Id header fallback |
| `test_build_envelope_auto_generates_trace_id` | 無任何 trace 來源時自動生成 uuid |
| `test_build_envelope_locale_defaults_to_zh_tw` | locale fallback 到 zh-TW |
| `test_build_envelope_persona_defaults_to_default` | persona_id fallback 到 "default" |
| `test_build_envelope_merges_metadata` | body + message metadata 合併 |
| `test_serialize_context_roundtrip` | serialize → dict 包含所有欄位 |
| `test_normalize_to_brain_message_preserves_all_context` | envelope → BrainMessage 所有欄位保留 |
| `test_normalize_to_brain_message_maps_message_type_to_role` | message_type 正確對應 role |
| `test_create_brain_message_for_system_role` | 可建立 system role 的 BrainMessage |
| `test_create_brain_message_for_assistant_role` | 可建立 assistant role 的 BrainMessage |
| `test_brain_message_metadata_is_defensive_copy` | metadata 修改不影響原始 context |

### 手動驗收

| 驗收標準 | 如何確認 |
|---------|---------|
| 所有請求進 brain 前都會先標準化 | `build_message_envelope` 已被所有 endpoint 呼叫 |
| locale / persona / trace 不會在中途遺失 | `test_normalize_to_brain_message_preserves_all_context` 通過 |
| stage output 有單元測試 | `test_message_envelope.py` 覆蓋 normalize + enrich + context 保留 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/protocol/message_envelope.py` | 修改 | 新增 BrainMessage / normalize_to_brain_message / create_brain_message |
| `brain/api/safety/guardrails.py` | 修改 | message_type 驗證加入 system / assistant |
| `brain/api/tests/test_message_envelope.py` | 新增 | message envelope 全覆蓋單元測試 |
| `docs/plans/TASK-16-brain-message-normalization.md` | 新增 | 計畫書 |
