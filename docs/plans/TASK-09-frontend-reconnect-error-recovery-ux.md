# TASK-09: Frontend Reconnect, Error, and Recovery UX

> Issue: [#19](https://github.com/CreateIntelligens/openVman/issues/19) — Frontend reconnect, error, and recovery UX
> Epic: #3
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

讓 client 對掉線、`server_error`、interrupt 都能自動恢復，並提供清楚的 UI 狀態提示。既有 `useAvatarChat.ts` 已有基本 exponential backoff（[useAvatarChat.ts:140-148](../../frontend/app/src/composables/useAvatarChat.ts)），本任務補齊：上限/抖動、queue/state 重置、UI 顯示、錯誤分類。

| 需求 | 說明 |
|------|------|
| 重連策略 | 指數退避 + 抖動（jitter）+ 最大重試次數，達上限後停止並提示用戶手動重連 |
| `server_error` UI | 依 `error_code` 分類顯示（recoverable / fatal / rate-limit），含 `retry_after_ms` 倒數 |
| Queue / state reset | 斷線或 interrupt 時清空 audio queue、重置 SPEAKING/THINKING state |
| 狀態視覺化 | IDLE / THINKING / SPEAKING / RECONNECTING / ERROR 五種狀態都有明確 UI 表現 |
| 可動作回饋 | ERROR / 達重試上限時提供「重新連線」按鈕 |

---

## 開發方法

### 架構

```
WebSocket onclose
    │
    ├─ flush audio queue (useAudioPlayer.flush())
    ├─ state = RECONNECTING
    ├─ delay = min(BASE * 2^attempt, MAX) + random jitter
    ├─ attempt < MAX_ATTEMPTS ?
    │     yes → setTimeout(connect, delay)
    │     no  → state = ERROR, show "重新連線" button
    └─ user clicks reconnect → reset attempt = 0, connect()

server_error event
    │
    ├─ classify(error_code)
    │     recoverable → toast + auto continue
    │     rate_limit  → toast with retry_after_ms countdown
    │     fatal       → ErrorOverlay + reconnect button
    └─ if fatal: flush queue, state = ERROR
```

### 重連參數

| 參數 | 值 | 說明 |
|------|----|------|
| `BASE_DELAY_MS` | 1000 | 第一次延遲 |
| `MAX_DELAY_MS` | 30000 | 上限 |
| `MAX_ATTEMPTS` | 6 | 約覆蓋 ~63s 後停止 |
| `JITTER` | ±25% | 防止驚群 |

### 錯誤分類表（依 `error_code`）

| error_code | 類型 | UI |
|-----------|------|----|
| `SESSION_EXPIRED` | recoverable | StatusToast + 自動重連，不阻塞輸入 |
| `RATE_LIMITED` | rate_limit | StatusToast，顯示 `retry_after_ms` 倒數 |
| `INVALID_INPUT` | recoverable | StatusToast 簡訊，繼續使用 |
| `BACKEND_UNAVAILABLE` | fatal | ErrorOverlay + 重新連線按鈕 |
| `VERSION_MISMATCH` | fatal | ErrorOverlay 不重連，顯示需升級訊息 |
| 預設（未列） | fatal | ErrorOverlay |

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 寫失敗測試 | jitter / max attempts / queue reset / 錯誤分類 | `frontend/app/src/composables/__tests__/useAvatarChat.spec.ts` |
| 2. 重連策略升級 | 加入 jitter + MAX_ATTEMPTS + 對外 `manualReconnect()` | `frontend/app/src/composables/useAvatarChat.ts` |
| 3. State 擴充 | 加入 `RECONNECTING`，斷線時 flush audio queue | 同上 + `useAudioPlayer.ts` |
| 4. 錯誤分類 | `classifyServerError(code)` → `'recoverable' \| 'rate_limit' \| 'fatal'` | `frontend/app/src/utils/errorClassifier.ts` |
| 5. UI 元件 | `StatusToast.vue`（既有）+ `ErrorOverlay.vue`（既有）接 store | `frontend/app/src/components/StatusToast.vue`、`ErrorOverlay.vue` |
| 6. State store | 集中管理 connection / error 狀態 | `frontend/app/src/stores/useConnectionStore.ts`（若無則新增） |
| 7. App 接線 | `App.vue` 訂閱 store 顯示 overlay / toast | `frontend/app/src/App.vue` |

### State machine

```
IDLE ──user_speak──▶ THINKING ──first chunk──▶ SPEAKING ──is_final + drain──▶ IDLE
  │                      │                          │
  │                      └──server_error fatal──────┘
  │                                                 │
  └────────────────────onclose────────────────────▶ RECONNECTING
                                                    │
                       attempt < MAX ──connect ok──▶ IDLE
                       attempt = MAX ──────────────▶ ERROR (manual reconnect)
```

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| 單元測試 | `cd frontend/app && npm run test -- useAvatarChat` | jitter 範圍、達上限停止、queue reset、錯誤分類 |
| 型別檢查 | `cd frontend/app && npx vue-tsc --noEmit` | error classifier / state enum 對齊 |
| Lint | `cd frontend/app && npm run lint` | 無 console.log |

### 手動驗收

| 驗收標準 | 如何確認 |
|---------|---------|
| reconnect is automatic and bounded | DevTools → Network → Offline，應自動重連最多 `MAX_ATTEMPTS` 次後出現「重新連線」按鈕 |
| client state recovers safely | 在 SPEAKING 中強制斷線，audio queue 立即排空，state 進入 RECONNECTING；恢復後可再次 user_speak |
| user-facing error feedback visible & actionable | 模擬後端回 `BACKEND_UNAVAILABLE` → ErrorOverlay 出現含按鈕；`RATE_LIMITED` → toast 顯示倒數 |

### 驗證指令

```bash
# 1. 單元測試
cd frontend/app && npm run test -- useAvatarChat

# 2. 手動斷線測試
docker compose up -d
# Chrome DevTools → Network → Offline → 觀察 RECONNECTING 狀態

# 3. server_error 模擬（在 brain 端強制送錯）
docker compose exec brain python -c "..."
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `frontend/app/src/composables/useAvatarChat.ts` | 修改 | 加入 jitter、MAX_ATTEMPTS、manualReconnect、queue flush |
| `frontend/app/src/composables/useAudioPlayer.ts` | 修改 | 暴露 `flush()`（與 TASK-07 對齊） |
| `frontend/app/src/utils/errorClassifier.ts` | 新增 | error_code → 類型映射 |
| `frontend/app/src/stores/useConnectionStore.ts` | 新增（若無） | 連線/錯誤狀態集中 |
| `frontend/app/src/components/StatusToast.vue` | 修改 | 接 store 顯示 toast + 倒數 |
| `frontend/app/src/components/ErrorOverlay.vue` | 修改 | 接 store + 重新連線按鈕 |
| `frontend/app/src/App.vue` | 修改 | 訂閱 store 顯示 overlay/toast |
| `frontend/app/src/composables/__tests__/useAvatarChat.spec.ts` | 新增 | 重連與錯誤分類測試 |
| `docs/plans/TASK-09-frontend-reconnect-error-recovery-ux.md` | 新增 | 計畫書 |

---

## 相依性與風險

- **相依 TASK-07**：`useAudioPlayer.flush()` 由 TASK-07 實作；本任務在斷線/interrupt 時呼叫它。
- **相依 TASK-03**（backend interrupt + unified error bridge）：`server_error` payload 結構與 `error_code` 列表來自 backend 約定，需與該 task 對齊。
- **風險**：若 backend 回應極快，重連抖動 + jitter 可能導致 race（連線未斷又開新 socket）— 需在 `connect()` 前確認舊 socket 已 close。
- **風險**：UI 狀態若未集中於 store，多個元件各自監聽 ws 會導致狀態不一致 — 強制走 `useConnectionStore`。
- **風險**：`MAX_ATTEMPTS = 6` 可能對行動網路切換情境太短，視實測再調整。
