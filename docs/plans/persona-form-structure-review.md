# 角色管理表格模式：潛在問題與「拆開存、送出時組合」的評估（Draft）

狀態：Draft，待外部審查（Codex／其他 agent）後決定。2026-11-27。

## 背景

後台「角色管理」有兩種顯示方式，改的是同一份檔案：

- 原始文件：直接編輯 `SOUL.md`、`AGENTS.md`（每個人設一份）與專案共用的 `GUARDRAILS.md`。
- 表格（簡易版）：前端把同一份 Markdown 依 `## 標題` 拆成欄位，存檔時再組回整份 Markdown 寫回。
  - SOUL：`## 角色設定`、`## 回應風格`；AGENTS：`## 角色與任務`；GUARDRAILS：`## 範圍限制`、`## 回覆格式`、`## 知識庫規則`。
  - 欄位以外的段落放進「其他內容」，存檔時依原位置寫回。
- Brain 回答時把整份檔案原文放進系統提示詞（`brain/api/core/prompt_builder.py`、`brain/api/knowledge/workspace.py::load_core_workspace_context`），不認欄位。
- 新專案建立時才寫入表格認得的標題（`workspace.py` 的 `NEW_PROJECT_TEMPLATES`）；既有專案不補，所以舊專案在表格模式整份會掉進「角色設定」一格。

## 相關程式

- 拆分與組回：`frontend/admin/src/utils/personaSections.ts`（325 行，測試 `personaSections.test.ts` 12 個）
- 表格畫面：`frontend/admin/src/components/personas/PersonaForm.tsx`
- 存檔 API：`brain/api/routes/personas.py` 的 `PUT /personas/soul`、`PUT /personas/agents`（直接整份覆寫，沒有 `base_hash` 衝突檢查）；保護規則走 `PUT /knowledge/document`（有 `base_hash`）
- 廠商帳號：只改得到 SOUL／AGENTS，改不到 GUARDRAILS

## 想確認的問題

1. 現行「單一 Markdown ↔ 欄位」來回轉換有哪些實際會發生的資料錯亂？請實際跑程式重現，例如：
   - 使用者在欄位內文打出 `## 回應風格`、`## 角色設定` 或其他 `## ` 標題，存檔後再讀，內容是否跑到別的欄位、重複或消失
   - 標題有全形空白、全形括號、後綴（`## 角色設定（中文）`）、大小寫或多餘空白
   - 程式碼區塊、`---` front matter、CRLF、只有 `#` 大標題、空欄位、同名標題出現兩次
   - 表格存檔後切到原始文件再切回來（或反過來）是否穩定（parse → serialize → parse 是否 idempotent）
2. 並行寫入：SOUL／AGENTS 沒有衝突檢查，兩個分頁、表格與原始文件、或兩個帳號同時改時，後存的整份覆寫先存的。實際影響多大、該怎麼補。
3. 架構選項比較，請給建議與理由：
   - A. 維持單一 Markdown，加強解析（例如欄位內文出現已知標題時跳脫、存檔前後做 round-trip 檢查）＋補 `base_hash`
   - B. 拆開存：每個欄位存成獨立資料（例如 `persona.json` 或每欄一個檔），Brain 送提示詞時再依固定順序組成 Markdown；原始文件模式改成「唯讀預覽組合結果」或保留為進階模式
   - C. 其他做法
   每個選項請說明：既有專案的搬遷方式（舊格式、自訂標題）、與廠商權限／保護規則的關係、Brain 提示詞快取（`_CORE_CONTEXT_CACHE` 以檔案 mtime 判斷）、備份還原、回滾成本。
4. 若選 B，最小可行範圍是什麼、哪些地方一定要改（前端、Brain 讀取、API、搬遷腳本、測試）。

## 已知事實（已查證）

- `PUT /personas/soul`、`PUT /personas/agents` 直接 `write_text_atomic` 整份覆寫，沒有衝突檢查（`brain/api/routes/personas.py`）。
- 表格模式只認與欄位名稱完全相同的 `## ` 標題；開頭的 `# ` 大標題不算欄位。
- 2026-11-27 已讓「其他內容」在只有 `# ` 大標題時不顯示（commit 32d81bb1）。
- 鶴記（proj-0cc5c610b4）2026-11-27 已改成表格認得的標題，兩個人設＋專案保護規則。

## 希望的回覆形式

- 每個潛在問題：CONFIRMED（附重現步驟與輸出）／PLAUSIBLE／NOT AN ISSUE
- 架構建議：選哪個、理由、主要風險、粗估改動範圍
- 600 字內

## 決定（2026-11-27）

- **現在做 A**（分支 `fix/persona-save-safety`）：維持單一 Markdown，補強解析與並行寫入。
  - SOUL／AGENTS 的 GET 回 `content_hash`，PUT 收 `base_hash`，被改過回 409；檔案不存在以空字串的雜湊比對（`PUT /knowledge/document` 同規則），比對與寫入在 `document_save_lock` 跨行程鎖裡。表格與原始文件模式都帶 `base_hash`，409 時保留草稿。
  - `personaSections` 只認頂格、不在程式碼區塊與開頭 front matter 裡的 `## `；清空最後一欄留空標題；其他內容的段落順序照使用者排的存；存檔前做 round-trip 檢查，讀回不一樣就不存。
- **B 之後再做**：拆開存時欄位名稱與 jtai 相容，用 `role_scope`、`scope_limits`、`response_style`、`knowledge_rules`。搬遷、Brain 組提示詞與原始文件模式的去留到時另寫計畫。
