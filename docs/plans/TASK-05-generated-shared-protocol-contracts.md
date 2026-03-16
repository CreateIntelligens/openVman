# TASK-05: Generate Shared TS and Python Protocol Types

> Issue: #15 — Generate shared TS and Python protocol types
> Epic: #2
> Branch: `feature/brain`
> Status: **Done**

---

## 開發需求

讓 TypeScript 與 Python 共用同一份通訊協定型別來源，消除手動維護重複型別定義的風險。

| 需求 | 說明 |
|------|------|
| 單一真相來源 | 所有 event schema 定義於 `contracts/schemas/v1/*.json` |
| TS 型別產出 | 從 JSON Schema 自動生成 TypeScript interfaces + union types |
| Python 型別產出 | 從 JSON Schema 自動生成 Pydantic v2 models + TypeAdapter |
| 前後端統一 import | frontend / backend 都從 `contracts/generated/` import，不再手抄 |
| CI 防 drift | PR/push 時自動偵測 generated code 是否與 schema 同步 |

---

## 開發方法

### 架構

```
contracts/schemas/v1/*.json              ← 唯一真相來源 (JSON Schema)
        │
contracts/scripts/generate_protocol_contracts.py  ← 程式碼產生器
        │
        ├─► contracts/generated/python/openvman_contracts/
        │       ├─ __init__.py
        │       ├─ protocol_contracts.py   ← Pydantic models + unions + adapters
        │       └─ py.typed
        └─► contracts/generated/typescript/
                └─ protocol-contracts.d.ts  ← TS interfaces + unions + constants
```

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 寫失敗測試 | 新增測試確認 generated module 可被 import | `brain/api/tests/test_protocol_events.py` |
| 2. 實作 generator | 讀取 manifest + schema → 輸出 TS/Python | `contracts/scripts/generate_protocol_contracts.py` |
| 3. 重構 backend | 改為從 generated Python package import event models | `brain/api/protocol/protocol_events.py` |
| 4. 重構 frontend | 改為從 generated TS contracts import types | `brain/web/src/protocol/validators.ts`, `tsconfig.json` |
| 5. CI drift 偵測 | `--check` 模式 + pytest + tsc --noEmit | `.github/workflows/contracts.yml` |
| 6. 端對端驗證 | 本地跑 generator → tests → typecheck → smoke | 全部 |

### 關鍵技術決策

- **JSON Schema** 作為中立格式，不綁定任何語言
- **Generator 而非 runtime 解析**：build time 產生靜態型別，零 runtime 成本
- **`--check` 模式**：CI 比對 generated output vs schema，不一致即 fail
- **Pydantic discriminated union**：用 `Field(discriminator='event')` 讓 Python 側做高效 dispatch

---

## 驗收方法

### 自動驗收 (CI)

`.github/workflows/contracts.yml` 在 PR 與 push to main 時自動執行：

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| Generated code 同步 | `python3 contracts/scripts/generate_protocol_contracts.py --check` | schema 變更後必須重新 generate |
| Backend 測試 | `python3 -m pytest brain/api/tests/test_protocol_events.py -v` | Pydantic models 正確解析/拒絕 payloads |
| Frontend 型別檢查 | `npx tsc --noEmit` | TS types 與 validators 一致無錯誤 |

### 手動驗收

| 驗收標準 | 如何確認 | 狀態 |
|---------|---------|------|
| frontend/backend import from same schema source | 檢查兩邊 import 路徑都指向 `contracts/generated/` | ✅ |
| no duplicated manual type definitions | Python 從 `openvman_contracts.protocol_contracts` import；TS 從 `contracts/generated/typescript/protocol-contracts` import | ✅ |
| CI catches protocol drift | `.github/workflows/contracts.yml` 執行 `--check` + tests + typecheck | ✅ |

### 驗證指令 (本地執行)

```bash
# 1. 重新產生 contracts
python3 contracts/scripts/generate_protocol_contracts.py

# 2. 檢查是否同步 (CI 用這個)
python3 contracts/scripts/generate_protocol_contracts.py --check

# 3. 跑 backend 測試
python3 -m pytest brain/api/tests/test_protocol_events.py -v

# 4. 跑 frontend typecheck
cd brain/web && npx tsc --noEmit
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `contracts/schemas/v1/manifest.json` | 既有 | Event 註冊清單 |
| `contracts/schemas/v1/*.schema.json` | 既有 | 各 event 的 JSON Schema |
| `contracts/scripts/generate_protocol_contracts.py` | 新增 | 程式碼產生器 |
| `contracts/generated/python/openvman_contracts/protocol_contracts.py` | 產生 | Python Pydantic models |
| `contracts/generated/python/openvman_contracts/__init__.py` | 產生 | Python package init |
| `contracts/generated/typescript/protocol-contracts.d.ts` | 產生 | TS type declarations |
| `brain/api/protocol/protocol_events.py` | 修改 | 改 import generated models |
| `brain/web/src/protocol/validators.ts` | 修改 | 改 import generated types |
| `brain/web/src/protocol/validators.smoke.ts` | 修改 | Smoke test 配合新 imports |
| `brain/web/tsconfig.json` | 修改 | 加 contracts path mapping |
| `.github/workflows/contracts.yml` | 新增 | CI drift detection |
| `brain/api/tests/test_protocol_events.py` | 修改 | 測試 generated contracts |
