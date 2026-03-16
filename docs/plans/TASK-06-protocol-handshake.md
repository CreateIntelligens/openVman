# TASK-06: Protocol Handshake and Compatibility Checks

> Issue: #16 — Protocol handshake and compatibility checks
> Epic: #2
> Branch: `feature/brain`
> Status: **In Progress**

---

## 開發需求

完成連線握手時的協定版本檢查，讓 client 與 server 在 session 建立當下即可判斷版本是否相容。

| 需求 | 說明 |
|------|------|
| `server_init_ack` 事件 | Server 收到 `client_init` 後回覆連線確認（含 session_id, server_version, status） |
| 版本相容性規則 | 依 Semantic Versioning — MAJOR 版本相同即相容（§6） |
| 不相容拒絕 | 版本不相容時 server 回傳 `status: "version_mismatch"` + 原因訊息 |
| 前後端共用型別 | `server_init_ack` schema 走既有 contracts pipeline（JSON Schema → generator → TS/Python） |
| 測試覆蓋 | handshake 成功/失敗、版本比對、payload 驗證皆有測試 |

---

## 開發方法

### 架構

```
client_init (client → server)
    │
    ▼
perform_handshake()
    ├─ validate_client_event(payload)
    ├─ check_version_compatible(client_version, server_version)
    │
    ▼
server_init_ack (server → client)
    ├─ status: "ok"              ← 相容
    └─ status: "version_mismatch" ← 不相容，含 message 說明
```

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 新增 schema | `server_init_ack.schema.json` + 更新 manifest | `contracts/schemas/v1/` |
| 2. 產生 contracts | 執行 generator → `ServerInitAckEvent` | `contracts/generated/` |
| 3. 寫失敗測試 | handshake 成功/失敗、version check、ack 驗證 | `brain/api/tests/test_protocol_events.py` |
| 4. Backend handshake | `perform_handshake()` + `check_version_compatible()` | `brain/api/protocol/protocol_events.py` |
| 5. Frontend validators | `validateServerInitAck` + `checkVersionCompatible()` | `brain/web/src/protocol/validators.ts` |
| 6. Smoke test | 加入 server_init_ack 驗證 | `brain/web/src/protocol/validators.smoke.ts` |

### `server_init_ack` Schema 設計

```json
{
  "event": { "const": "server_init_ack" },
  "session_id": { "type": "string", "minLength": 1 },
  "server_version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" },
  "status": { "enum": ["ok", "version_mismatch"] },
  "message": { "type": "string" },
  "timestamp": { "type": "integer", "minimum": 0 }
}
```
Required: event, session_id, server_version, status, timestamp

### 版本相容性規則

```python
def check_version_compatible(client_version: str, server_version: str) -> bool:
    return client_version.split(".")[0] == server_version.split(".")[0]
```

MAJOR 相同即相容（`1.0.0` ↔ `1.2.0` ✓，`1.0.0` ↔ `2.0.0` ✗）。

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| Generated code 同步 | `python3 contracts/scripts/generate_protocol_contracts.py --check` | 新 schema 已被 generator 處理 |
| Backend 測試 | `python3 -m pytest brain/api/tests/test_protocol_events.py -v` | handshake + version check + ack 驗證 |
| Frontend 型別檢查 | `cd brain/web && npx tsc --noEmit` | ServerInitAckEvent 型別正確 |

### 手動驗收

| 驗收標準 | 如何確認 |
|---------|---------|
| version mismatch is detectable at connect time | `perform_handshake()` 在 MAJOR 不同時回傳 `status: "version_mismatch"` |
| handshake result is logged and test-covered | pytest 覆蓋成功/失敗/非法 payload 場景 |
| incompatible clients fail with explicit errors | ack 包含 `message` 欄位說明拒絕原因 |

### 驗證指令

```bash
# 1. Generator check
python3 contracts/scripts/generate_protocol_contracts.py --check

# 2. Backend tests
python3 -m pytest brain/api/tests/test_protocol_events.py -v

# 3. Frontend typecheck
cd brain/web && npx tsc --noEmit
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `contracts/schemas/v1/server_init_ack.schema.json` | 新增 | server_init_ack payload schema |
| `contracts/schemas/v1/manifest.json` | 修改 | 加入 server_init_ack 事件 |
| `contracts/generated/python/openvman_contracts/protocol_contracts.py` | 產生 | 新增 ServerInitAckEvent model |
| `contracts/generated/typescript/protocol-contracts.d.ts` | 產生 | 新增 ServerInitAckEvent interface |
| `brain/api/protocol/protocol_events.py` | 修改 | 新增 perform_handshake + check_version_compatible |
| `brain/web/src/protocol/validators.ts` | 修改 | 新增 validateServerInitAck + checkVersionCompatible |
| `brain/web/src/protocol/validators.smoke.ts` | 修改 | 加入 server_init_ack smoke test |
| `brain/api/tests/test_protocol_events.py` | 修改 | 新增 handshake 相關測試 |
| `docs/plans/TASK-06-protocol-handshake.md` | 新增 | 計畫書 |
