# TASK-01: Backend Message Envelope and Trace Context

> Issue: #11 — Backend message envelope and trace context
> Epic: #1
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

建立 backend 內部 message envelope 與 trace context 基礎，讓所有 inbound 事件統一轉成內部格式，並在 logs 中可追蹤。

| 需求 | 說明 |
|------|------|
| message envelope shape | 定義內部訊息封裝格式，含 content 與 context |
| trace context fields | `trace_id`、`session_id`、`client_id`、`received_at` 等欄位 |
| inbound normalization | 將 websocket / HTTP 事件轉成內部 envelope |
| validation | 非法 payload 回傳結構化錯誤 |

---

## 驗收標準對照

| 驗收標準（Issue #11） | 實作方式 |
|----------------------|---------|
| all inbound events are converted into a typed internal envelope | `build_message_envelope()` 將 request + payload 轉為 `MessageEnvelope` |
| envelope fields are visible in logs | `RequestContext` 含 trace_id / session_id，middleware 注入 `request.state.trace_id` |
| invalid messages fail with structured errors | 缺欄位或格式錯誤時拋 `ValueError`，由 endpoint 轉為 protocol error response |

---

## 設計

### 核心資料結構

```text
RequestContext
  ├─ trace_id: str (from X-Trace-Id header or auto-generated UUID)
  ├─ session_id: str
  ├─ message_type: str (user / tool / system / assistant / control)
  ├─ channel: str (default: web)
  ├─ locale: str (default: zh-TW)
  ├─ persona_id: str (default: default)
  ├─ project_id: str (default: default)
  ├─ client_ip: str
  └─ metadata: dict

MessageEnvelope
  ├─ content: str
  └─ context: RequestContext

BrainMessage
  ├─ role: str (user / assistant / system / tool)
  ├─ content: str
  └─ context: RequestContext
```

### Trace 流向

```text
HTTP header (X-Trace-Id) → middleware → request.state.trace_id
  → build_message_envelope() → RequestContext.trace_id
  → BrainMessage.context.trace_id → logs / observability
```

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_build_envelope_from_structured_payload` | 結構化 payload 正確解析 |
| `test_build_envelope_from_legacy_payload` | 舊格式 payload 相容處理 |
| `test_trace_id_from_header` | 從 header 取得 trace_id |
| `test_trace_id_auto_generated` | 無 header 時自動生成 UUID |
| `test_metadata_merging` | metadata 正確合併 |
| `test_normalize_to_brain_message` | envelope 轉 BrainMessage 正確 |
| `test_create_brain_message_for_internal_stages` | 系統/助理訊息建立 |

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `brain/api/protocol/message_envelope.py` | RequestContext、MessageEnvelope、BrainMessage 與轉換函式 |
| `brain/api/tests/test_message_envelope.py` | 測試 |
