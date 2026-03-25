# TASK-04: Shared Protocol Schema Definitions and Validators

> Issue: #14 — Shared protocol schema definitions and validators
> Epic: #2
> Branch: `feature/brain`
> Status: **Done**

---

## 開發需求

建立核心事件的 canonical schema 定義，並提供前後端一致的 runtime validation。

| 需求 | 說明 |
|------|------|
| 機器可讀 schema | 以 JSON Schema (draft 2020-12) 定義所有 core event payloads |
| 版本化 | Schema 放在 `contracts/schemas/v1/` 下，由 `manifest.json` 註冊 |
| 涵蓋 5 個核心事件 | `client_init`, `user_speak`, `client_interrupt`, `server_stream_chunk`, `server_error` |
| Backend runtime validation | Python Pydantic v2 models + discriminated union validator |
| Frontend runtime validation | TypeScript runtime validator，逐欄位型別檢查 |
| 一致的錯誤格式 | 前後端都用 `ProtocolValidationError`，帶 version / event / details |

---

## 開發方法

### 架構

```
contracts/schemas/v1/
  ├─ manifest.json              ← 事件註冊清單 (protocol name, version, events)
  ├─ client_init.schema.json    ← client → server: 初始化握手
  ├─ user_speak.schema.json     ← client → server: 使用者語音/文字
  ├─ client_interrupt.schema.json ← client → server: 中斷
  ├─ server_stream_chunk.schema.json ← server → client: 串流回應
  └─ server_error.schema.json   ← server → client: 錯誤

brain/api/protocol/protocol_events.py   ← Python validator (Pydantic)
frontend/admin/src/protocol/validators.ts    ← TypeScript validator (手寫 runtime)
```

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 寫失敗測試 | 覆蓋 contract loading、合法/非法 payload 驗證 | `brain/api/tests/test_protocol_events.py` |
| 2. 定義 JSON Schema | manifest + 5 個 event schema，帶 `additionalProperties: false` | `contracts/schemas/v1/*.json` |
| 3. 實作 backend validator | contract loader + Pydantic models + validation API | `brain/api/protocol/protocol_events.py` |
| 4. 實作 frontend validator | TS runtime validators + 逐欄位型別檢查 | `frontend/admin/src/protocol/validators.ts` |
| 5. 端對端驗證 | backend tests + frontend typecheck + smoke test | 全部 |

### 關鍵技術決策

- **JSON Schema 而非 Protobuf/Avro**：保持低門檻，前端可直接 import JSON
- **Pydantic discriminated union**：用 `event` 欄位自動 dispatch 到正確 model
- **`additionalProperties: false`**：嚴格模式，拒絕非預期欄位
- **前端手寫 validator 而非 ajv**：更精確的錯誤訊息，零額外 dependency
- **Versioned directory**：`v1/` 結構預留未來升級路徑

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| Backend 測試 | `python3 -m pytest brain/api/tests/test_protocol_events.py -v` | contract loading、合法 payload 通過、非法 payload 被拒絕 |
| Frontend 型別檢查 | `cd frontend/admin && npx tsc --noEmit` | validators.ts 型別正確 |
| Frontend smoke test | 執行 `validators.smoke.ts` | runtime validation 邏輯正確 |

### 手動驗收

| 驗收標準 | 如何確認 | 狀態 |
|---------|---------|------|
| schemas are machine-readable and versioned | `contracts/schemas/v1/manifest.json` 存在且包含 version + 5 個 events | ✅ |
| runtime validation exists for inbound and outbound | Python: `validate_client_event()` / `validate_server_event()`；TS: 同名函式 | ✅ |
| invalid payloads are rejected consistently | 缺欄位 → error、多餘欄位 → error、錯誤型別 → error，前後端行為一致 | ✅ |

### 驗證指令 (本地執行)

```bash
# 1. Backend tests
python3 -m pytest brain/api/tests/test_protocol_events.py -v

# 2. Frontend typecheck
cd frontend/admin && npx tsc --noEmit

# 3. Frontend smoke (in Docker)
cd frontend/admin && npx tsc --noEmit
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `contracts/schemas/v1/manifest.json` | 新增 | Event 註冊清單 |
| `contracts/schemas/v1/client_init.schema.json` | 新增 | client_init payload schema |
| `contracts/schemas/v1/user_speak.schema.json` | 新增 | user_speak payload schema |
| `contracts/schemas/v1/client_interrupt.schema.json` | 新增 | client_interrupt payload schema |
| `contracts/schemas/v1/server_stream_chunk.schema.json` | 新增 | server_stream_chunk payload schema |
| `contracts/schemas/v1/server_error.schema.json` | 新增 | server_error payload schema |
| `brain/api/protocol/protocol_events.py` | 新增 | Python contract loader + validator |
| `frontend/admin/src/protocol/validators.ts` | 新增 | TypeScript runtime validator |
| `frontend/admin/src/protocol/validators.smoke.ts` | 新增 | Frontend smoke test |
| `frontend/admin/tsconfig.json` | 修改 | 啟用 JSON import + path mapping |
| `brain/api/tests/test_protocol_events.py` | 新增 | Backend 測試 |
