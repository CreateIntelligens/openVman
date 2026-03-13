# Core Protocol Event Schemas Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立可版本化、機器可讀的核心事件 schema，並提供前後端 runtime validation。

**Architecture:** 以 versioned JSON Schema 作為 canonical contract，放在 repo 內作為單一真相來源。Python 端以 Pydantic model 與 schema loader 提供 backend validator；前端以 TypeScript runtime validator 對同一版本 contract 做檢查與一致錯誤格式封裝。

**Tech Stack:** JSON Schema, Python 3.12, Pydantic v2, TypeScript, Vite

---

### Task 1: Write failing backend tests for protocol contract loading and validation

**Files:**
- Create: `brain/api/tests/test_protocol_events.py`

**Step 1: Write the failing test**

覆蓋以下行為：
- 載入 versioned schema manifest
- 驗證合法 `client_init`
- 驗證合法 `server_stream_chunk`
- 拒絕缺欄位與多餘欄位
- 拒絕不支援的 version

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest brain/api/tests/test_protocol_events.py -v`

**Step 3: Write minimal implementation**

新增 contract loader 與 validator，先讓 backend 測試轉綠。

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest brain/api/tests/test_protocol_events.py -v`

### Task 2: Add canonical machine-readable versioned schemas

**Files:**
- Create: `contracts/schemas/v1/manifest.json`
- Create: `contracts/schemas/v1/client_init.schema.json`
- Create: `contracts/schemas/v1/user_speak.schema.json`
- Create: `contracts/schemas/v1/client_interrupt.schema.json`
- Create: `contracts/schemas/v1/server_stream_chunk.schema.json`
- Create: `contracts/schemas/v1/server_error.schema.json`

**Step 1: Define manifest and per-event JSON Schema**

每個 schema 都帶 `$id`、`title`、`direction`、`contract_version` 與 `additionalProperties: false`。

**Step 2: Verify backend loader reads schemas**

Run: `python3 -m pytest brain/api/tests/test_protocol_events.py -v`

### Task 3: Implement backend validators

**Files:**
- Create: `brain/api/protocol_events.py`

**Step 1: Add discriminated event models**

建立 client/server 各自的 Pydantic models 與 union validator。

**Step 2: Add consistent validation API**

提供：
- `load_protocol_contract(version)`
- `validate_client_event(payload, version)`
- `validate_server_event(payload, version)`
- `ProtocolValidationError`

**Step 3: Re-run backend tests**

Run: `python3 -m pytest brain/api/tests/test_protocol_events.py -v`

### Task 4: Implement frontend runtime validators

**Files:**
- Create: `brain/web/src/protocol/validators.ts`
- Modify: `brain/web/tsconfig.json`

**Step 1: Import shared schema manifest**

開啟 JSON import，讓前端可讀 versioned contract metadata。

**Step 2: Add runtime validators**

提供：
- `validateClientEvent(payload, version)`
- `validateServerEvent(payload, version)`
- `ProtocolValidationError`

**Step 3: Add simple smoke entry for validation**

讓 Node/tsc 可執行一個最小 smoke check。

### Task 5: Verify end-to-end contract artifacts

**Files:**
- Optional: `brain/web/src/protocol/validators.smoke.ts`

**Step 1: Run backend tests**

Run: `python3 -m pytest brain/api/tests/test_protocol_events.py -v`

**Step 2: Run frontend type check**

Run: `docker compose -f brain/docker-compose.yml exec web npx tsc --noEmit`

**Step 3: Run frontend build**

Run: `docker compose -f brain/docker-compose.yml exec web npm run build`

**Step 4: Run frontend validator smoke**

Run: `docker compose -f brain/docker-compose.yml exec web node /tmp/protocol-validator-smoke.mjs`
