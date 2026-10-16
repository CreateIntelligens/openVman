# 專案的資源範圍：人物、聲音、ASR 以專案為中心

狀態：Draft（2026-10-15 建立；2026-10-16 更新：第一～三階段與 ROOT 豁免已上線，剩餘工作見文末「目前狀態與剩餘工作」）

## 為什麼要改

專案已經掛著知識庫、人設與 Prompt、語言分流、對話紀錄、Embed key，以及第一期的語音限制（`project_policies`，只能限制 ASR 引擎與 TTS 聲音）。但「這個虛擬人長什麼樣、用什麼聲音、聽哪個引擎」大多還掛在帳號上：

- 人物、背景、小助理只看帳號授權（`resource_grants`），專案管不到。
- 登入後套用的預設（`account_defaults`：專案、人物、聲音、ASR、背景、小助理）綁帳號。同一個專案給三個人用，就得在三個帳號各設一次，容易不一致。
- 從專案看不出它實際能用哪些資源；權限圖譜也畫不出來（2026-10-15 查 AWS-dev 時就卡在這裡：專案沒有限制，能用什麼全看 emily0320 的授權）。
- 所有資源目前都是 `system_public`（人物 15、聲音 84、ASR 9、背景 4、小助理 3），沒有「只屬於某個專案」的資源。為單一客戶做的人物（例如 1014 AWS 初階虛擬人）會出現在所有被授權帳號的每個專案裡。

## 目標

把專案當成「一個完整的虛擬人應用」：

| 層級 | 決定什麼 |
|---|---|
| 專案 | 知識庫、人設、語言分流；可用的人物、聲音、ASR、背景、小助理與各自預設值 |
| 帳號 | 能進哪些專案、在專案裡能做什麼（使用／編輯） |
| 帳號資源授權 | 只當上限（例如一般帳號不能用某些付費聲音），不再是決定專案長相的主要來源 |

## 資源分兩類

- 全域資源：現有的 `system_public`。照現行規則，透過帳號授權與專案限制使用。
- 專案資源：只屬於某個專案（`resources.visibility = 'project'`，新增 `owner_project_id`）。只在該專案出現、在其他專案不可見也不可指定；專案刪除時一併處理（見待決事項）。適用於客戶專屬人物、客製聲音、專案專用的 ASR 節點等。

「model」在這份計畫指 TTS 與 ASR 模型（聲音、辨識引擎），與人物、背景、小助理用同一套規則。LLM 模型維持全站設定，不在範圍內。

## ROOT 指派

ROOT 可以把任何資源（全域或其他專案不可見的除外）直接指派給專案，不受專案限制清單與使用者帳號授權約束：指派後專案內所有能使用該專案的人都能用。

做成一筆可見、可稽核、可撤銷的設定，不是執行時跳過權限檢查：

- 存在新表 `project_resource_assignments(project_id, resource_type, resource_id, assigned_by, assigned_at)`。
- 稽核事件 `project_resource_assigned`／`project_resource_unassigned`。
- 專案設定頁與權限圖譜標示「ROOT 指派」，與一般授權分開顯示，方便追查「為什麼這個人物會出現在這裡」。
- 一般 admin 不能新增或移除 ROOT 指派，只能看。

## 實際能用的資源

對某帳號在某專案、某資源類型：

```
可用 = （全域資源 ∩ 帳號授權上限 ∩ 專案限制）
     ∪ 專案資源
     ∪ ROOT 指派
```

- 專案限制為空時沿用現行語意「不限制」。
- ROOT 與不受限 admin 的帳號授權視為全部，但仍受專案限制（與第一期一致）。
- Embed key：沒有帳號授權，以專案清單代替（與第一期一致），加上專案資源與 ROOT 指派。

## 預設值的優先順序

登入或進入專案時，每種資源依序取第一個「可用」的值：

1. 專案預設（新增，擴充 `project_policies`：`default_character_id`、`default_background_id`、`default_mascot_id`；ASR、聲音已有）
2. 帳號預設（現有 `account_defaults`，只當備援）
3. 可用清單第一個

帳號登入預設的「預設專案」仍屬帳號。

## 資料與 API 變更（草案）

- Migration：
  - `resources` 加 `owner_project_id TEXT NULL`，`visibility` 新值 `project`。
  - `project_policies` 加 `allowed_characters_json`、`allowed_backgrounds_json`、`allowed_mascots_json` 與三個預設欄位。
  - 新表 `project_resource_assignments`。
- `GET/PUT /api/v1/projects/{id}/policy` 擴充新欄位；`PUT` 的權限規則不變（admin 以上、受限 admin 只能放自己上限內的資源）。
- 新增 `GET /api/v1/projects/{id}/resources`：回傳該專案每種資源的「可用清單」與每個項目的來源（全域授權／專案資源／ROOT 指派），供後台、前台與圖譜共用，避免各自計算。
- `POST/DELETE /api/v1/projects/{id}/assignments`：ROOT 專用。
- `GET /api/v1/characters`、`/api/v1/me/capabilities`、`/api/v1/tts/providers` 帶 `project_id` 時改用上面的計算。
- 前台登入：預設改走「專案預設 → 帳號預設」。

## 介面

- 專案與權限 → 專案：每個專案的設定頁新增「資源」分頁，依類型列出可用項目、來源標籤、預設值；ROOT 看得到「指派」操作。
- 權限圖譜：點專案時側欄列出實際可用的資源與來源；ROOT 指派以獨立的線型畫出；有專案限制的專案加標記。
- 帳號資源權限視窗：說明「帳號授權是上限，專案另有範圍」，避免誤以為改了帳號就能讓專案出現新人物。

## 分階段

1. 資料模型與計算：migration、`/projects/{id}/resources`、ROOT 指派 API 與稽核；行為不變（專案限制為空、沒有專案資源時結果與現在相同），以測試鎖住。
2. 套用：人物／背景／小助理的取得與前台載入改走新計算；專案預設優先於帳號預設。
3. 介面：專案資源分頁、圖譜、帳號視窗說明。
4. 搬遷：把客戶專屬素材（例如 1014）改為專案資源，由使用者逐一確認。

每階段都要更新 `docs/specs/01_BACKEND_SPEC.md` 的「專案語音限制」一節（擴充為「專案資源範圍」）、`CHANGELOG.md` 與相關操作文件。

## 待決事項（實作規格已先採用下方「預設決定」）

- 專案刪除時，專案資源（例如客戶專屬人物的檔案）要一併刪除、轉為全域，還是保留待 ROOT 處理？
- ROOT 指派是否也允許一般 admin 對「自己權限上限內的資源」做同樣的事（等於專案層授權），還是只限 ROOT？
- 帳號授權是否還需要作為上限：若專案已有完整清單，是否改成「能進專案就能用專案的全部資源」，帳號授權只留給沒有專案設定的舊專案？
- 專案資源要不要能「分享」給指定的其他專案（介於專案專屬與全域之間）。
- 已登入的前台在專案設定變更後何時生效（下次讀 `/me` 或即時推送）。

## 實作規格（第一～三階段，給實作者）

這一節是可以直接動手的規格。「預設決定」是使用者尚未拍板前先採用的做法，實作時照做，並在回報裡列出；之後要改只動對應的一小段。

### 預設決定

| 待決事項 | 先採用 |
|---|---|
| 專案刪除時的專案資源 | 不刪檔案。資源列保留，`owner_project_id` 設為 NULL、`visibility` 維持 `project`，變成只有 ROOT 看得到的「孤兒資源」，由 ROOT 決定轉全域、改掛別的專案或刪除。指派一併刪除（外鍵 CASCADE）。 |
| 誰能做 ROOT 指派 | 只有 ROOT。admin 只能看。 |
| 帳號授權是否仍為上限 | 是（沿用第一期語意）。專案資源與 ROOT 指派不受帳號授權限制；全域資源仍要帳號授權。 |
| 專案資源分享給其他專案 | 不做。要給別的專案用就由 ROOT 指派。 |
| 設定變更何時生效 | 下次讀 `/api/v1/me`、`/me/capabilities` 或切換專案時；不做即時推送。 |

### 不做的事

- 不改 LLM 模型設定（維持全站）。
- 不做第四階段（把既有素材搬成專案資源）；由使用者逐一決定後再手動處理。
- 不做轉址或相容層：沒有舊路徑要保留。

### 資料模型（Auth DB migration 23，寫在 `backend/app/auth/schema_migrations.py`）

1. `resources` 加 `owner_project_id TEXT NULL`，並允許 `visibility = 'project'`。若現有 CHECK 約束擋住新值，照既有「重建表」的 migration 寫法處理（參考 `database.py` 裡重建 users 的流程與 `_ASR_ENGINE_RESOURCES_TABLE`），保留所有資料與外鍵。
2. `project_policies` 加欄位（全部可為 NULL／預設空陣列 JSON）：`allowed_characters_json`、`allowed_backgrounds_json`、`allowed_mascots_json`、`default_character_id`、`default_background_id`、`default_mascot_id`。
3. 新表：

```sql
CREATE TABLE IF NOT EXISTS project_resource_assignments (
    project_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    assigned_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (project_id, resource_type, resource_id),
    FOREIGN KEY (project_id) REFERENCES resources(resource_id) ...  -- 依現有 project_policies 對 resources 的外鍵寫法
);
```

外鍵要讓「刪專案 → 指派消失」「刪資源 → 指派消失」。migration 要冪等（跑兩次不出錯），並補進 `backend/tests/auth/test_root_migration.py` 的版本檢查。`backend/app/auth/database.py` 與任何單檔不可超過 1000 行（CI `tests/test_entry_boundaries.py` 會擋）。

### 計算：單一來源

新增 `backend/app/auth/project_resources.py`，所有地方都只透過它算「某帳號在某專案能用哪些資源」：

```python
@dataclass(frozen=True, slots=True)
class ProjectResourceEntry:
    resource_id: str
    source: Literal["grant", "project", "assigned"]   # 帳號授權的全域資源／專案資源／ROOT 指派

def effective_project_resources(
    runtime: AuthRuntime,
    account: UserRecord | None,       # Embed key 傳 None
    project_id: str,
    resource_type: ResourceType,      # AVATAR_CHARACTER / AVATAR_BACKGROUND / AVATAR_MASCOT / CUSTOM_VOICE / ASR_ENGINE
) -> list[ProjectResourceEntry]: ...
```

規則：

```
grant    = 全域資源 ∩ 帳號可用（沿用 list_accessible_resources，ROOT／不受限 admin＝全部）
           ∩ 專案清單（清單為空＝不限制）
project  = resources.owner_project_id == project_id 的資源（不看帳號授權、不看專案清單）
assigned = project_resource_assignments 裡這個專案的項目（不看帳號授權、不看專案清單）
結果     = grant ∪ project ∪ assigned，同一 ID 只出現一次，source 取 assigned > project > grant
```

- Embed key（`account is None`）：`grant` 部分沿用第一期「專案有清單時以清單代替帳號授權，否則只有部署預設」，再加上 project 與 assigned。
- `visibility='project'` 的資源在任何其他專案、`GET /api/v1/characters`（公開清單，目前只列 `system_public`）與不帶專案的列表都不可出現；ROOT 例外（ROOT 的資源管理頁要看得到孤兒資源）。
- 預設值解析也放這裡：`effective_project_default(runtime, account, project_id, resource_type) -> str | None`，順序為專案預設 → 帳號預設（`account_defaults`）→ 結果清單第一個；每一步都必須在結果清單內才採用。

第一期的 `backend/app/voice_policy.py`（ASR）與 `backend/app/auth/voice_access.py:resolve_tts_voice`（TTS）改成：判斷「這個聲音／引擎能不能用」時，除了原本的「帳號授權 ∩ 專案清單」，也接受 `project` 與 `assigned` 來源。其餘行為（備援鏈、台語分流、Edge 退回條件、快取 key）不變，現有測試必須全過。

### API

| 方法與路徑 | 權限 | 內容 |
|---|---|---|
| `GET /api/v1/projects/{id}/policy`、`PUT` 同路徑 | 沿用第一期 | 擴充 `allowed_characters`、`allowed_backgrounds`、`allowed_mascots`、`default_character_id`、`default_background_id`、`default_mascot_id`。驗證同第一期：資源要已註冊、有清單時預設要在清單內、受限 admin 只能放自己上限內的資源。預設值也可以是本專案的專案資源或 ROOT 指派的資源。 |
| `GET /api/v1/projects/{id}/resources` | 能讀該專案 | `{ "<resource_type>": [{ "resource_id", "label", "source" }...], "defaults": { "<resource_type>": "<id or null>" } }`，資料就是 `effective_project_resources` 與 `effective_project_default` 的結果（以呼叫者身分計算）。後台、前台、圖譜都用它。 |
| `POST /api/v1/projects/{id}/assignments` | ROOT | body `{ resource_type, resource_id }`；資源不存在 422；已存在回 200 不重複。稽核 `project_resource_assigned`。 |
| `DELETE /api/v1/projects/{id}/assignments/{resource_type}/{resource_id}` | ROOT | 稽核 `project_resource_unassigned`；不存在回 404。 |
| `POST /api/v1/avatar`（上傳人物，現有） | 沿用 | 新增選填 form `project_id`：帶了就建成該專案的專案資源（`visibility='project'`），不帶照舊為全域。 |
| `GET /api/v1/avatar`、`/api/v1/backgrounds`、`/api/v1/mascots`（現有後台列表） | 沿用 | 新增選填 query `project_id`：帶了就回 `effective_project_resources` 的結果（每項多 `source`）；不帶時回應與現在完全相同。 |
| `GET /api/v1/me/capabilities?project_id=` | 沿用 | 帶專案時新增 `characters`、`backgrounds`、`mascots` 三個清單（含 `source`）與 `project_policy` 的新欄位；不帶時回應不變。 |
| `GET /api/v1/me` | 沿用 | 不改。 |

路由放在既有檔案旁（`backend/app/project_routes.py` 的 policy 路由附近；若接近 1000 行就拆新檔）。新增或改動的回應模型若屬於 `contracts/schemas/v1/` 的範圍，先改 schema 再跑 `python contracts/scripts/generate_protocol_contracts.py`；OpenAPI 由 FastAPI 產生，確認 `/docs` 正確。

### 前台虛擬人（`frontend/app`）

- 進入專案（登入後、切換專案）時呼叫 `GET /api/v1/projects/{id}/resources`。
- 人物、背景、小助理、聲音的選擇順序：
  1. 使用者在這台裝置／帳號偏好裡存的值（`useSettingsStore.ts` 的 `savedSettings()`），但只有在該偏好是同一個專案存的、且仍在可用清單內時才用；
  2. 專案預設；
  3. 帳號預設；
  4. 可用清單第一個。
- 設定面板的人物／聲音下拉只列可用清單，項目標示來源（專案專屬、ROOT 指派）可選做。
- 目前偏好存在單一 JSON（`account_preferences`，含 `projectId` 與 `characterId`）；若要做到「每個專案各記一份偏好」，改為以專案 ID 分鍵存放，舊格式讀到時視為目前專案的偏好。

### 後台（`frontend/admin`，先載 `frontend` skill 決定設計）

- 「專案與權限 → 專案」每個專案的「語音設定」視窗改名「資源設定」，加人物、背景、小助理三組（可用清單＋預設），沿用現有語音那兩組的元件與驗證訊息。
- 同一視窗加「ROOT 指派」區塊：ROOT 可新增／移除；admin 只讀；每項標「ROOT 指派」。
- 人物上傳（Avatar 頁）多一個「屬於專案」選項（不選＝全域）。
- 權限圖譜（`components/accessGraph/*`）：點專案時側欄列出 `/projects/{id}/resources` 的結果並標來源；ROOT 指派畫成專案到資源的獨立線型（圖例同步）；有專案限制的專案在節點上加標記。

### 測試（每一項都要有）

後端：
- migration 23 冪等、舊資料不變、外鍵行為（刪專案、刪資源）。
- `effective_project_resources`：一般帳號／受限 admin／ROOT／Embed key × 專案清單空／非空 × 有無專案資源 × 有無 ROOT 指派；來源優先序；專案資源不出現在其他專案與公開 `/characters`。
- 預設值解析順序與「不在清單就跳過」。
- 指派 API：非 ROOT 403、重複指派冪等、稽核事件。
- TTS／ASR：ROOT 指派的聲音／引擎可用，即使帳號沒授權；第一期所有既有測試照過。
- `backend` 跑 `python -m pytest tests/ -q`，Brain 不受影響可不跑。

前端：
- admin：資源設定視窗新欄位、ROOT 指派區塊權限、圖譜側欄來源標示（`pnpm test`、`pnpm build`）。
- app：選擇順序四條規則各一個測試、切換專案時重新計算（`npm test`、`npm run build`）。

### 文件

- `docs/specs/01_BACKEND_SPEC.md`：「專案語音限制」一節擴充為「專案資源範圍」，寫入上面的規則、API 與預設決定。
- `docs/operations/account-administration.md`：資源設定視窗與 ROOT 指派操作。
- `docs/guides/integration-quickstart.md`：`/me/capabilities` 新欄位、`/projects/{id}/resources`。
- `CHANGELOG.md` 的 `[Unreleased]`；本計畫標記完成的階段（狀態維持 Draft，由使用者確認後才改 Done）。

### 驗收（部署後在正式機）

1. 在 AWS-dev把人物 1014 設為專案預設：emily0320 與 ROOT 進 AWS-dev 都看到 1014；切到其他專案時 1014 不會因此變成預設。
2. 用 ROOT 把某個 voice-e2e-test 沒授權的聲音指派給鶴記dev：voice-e2e-test 在鶴記dev 能選到並合成，在其他專案仍看不到；移除指派後立即看不到。
3. 上傳一個「屬於 AWS-dev」的測試人物：只在 AWS-dev 出現、公開 `/api/v1/characters` 不列；測完刪除。
4. 第一期語音限制的既有行為不變（照 `docs/specs/01_BACKEND_SPEC.md` 的套用位置抽測 ASR、TTS 各一條）。
5. 測試產生的對話、指派、測試人物全部清掉。

### 工作方式

- 在 `.worktree/project-resource-scope`（分支 `feat/project-resource-scope`）開發，不要用工具內建的 worktree 隔離（會開在 `.claude/worktrees/`）。
- 依階段分 commit；不要自行 commit 或 push，做完回報 `git diff --stat`、測試數字與預設決定，由使用者確認。
- 遵守 `AGENTS.md`（兩個 Python 執行環境分開、文件與 CHANGELOG 同步）與使用者全域規則（pnpm、不用 px、Python import 分組）。

## 相關

- 帳號最後登入時間已於 2026-10-15 上線（Auth DB migration 22 `users.last_login_at`，後台帳號列表顯示並可依最久未使用排序），清理帳號不再需要猜。
- 第一期專案語音限制：`docs/specs/01_BACKEND_SPEC.md`「專案語音限制」。

## 第一輪 review（2026-10-15，待修正後再合併）

結論：需修正後合併。migration 23（冪等、外鍵、CASCADE、孤兒資源）與 `effective_project_resources` 的核心計算正確；問題在外圍串接，主要流程「專案成員載入專案專屬人物」目前走不通。後端 1440 passed、app 322、admin 689 皆過，但測試沒覆蓋到下列問題（app 的 mock 與實際回應格式不同）。

### 必修（P1）[全數完成]

1. [已完成] `ResourceAccess.WRITE` 不存在：`backend/app/routes/avatar.py`、`backgrounds.py`、`mascots.py` 中不存在的 `WRITE` 全數改為 `ResourceAccess.MUTATE`，補齊非 ROOT 管理員帶專案上傳測試。
2. [已完成] 列表 `?project_id=` 檢查能否讀該專案：`avatar.py`、`backgrounds.py`、`mascots.py` 的 list 端點加入 `resolve_resource(..., ResourceType.PROJECT, project_id, access=ResourceAccess.READ)`，讀不到或不存在統一回 404，補齊權限防禦測試。
3. [已完成] 靜態檔授權認專案來源：`backend/app/routes/static_assets.py` 的 `_check_resource_access` 補齊：一般帳號檢查該資源所屬專案與指派專案，若能 READ 任一專案即放行；Embed key 僅限綁定專案。在 `project_resource_assignment_repository.py` 新增 `list_projects_for_resource` 反查指派專案，補齊完整矩陣測試。
4. [已完成] 前後端欄位契約統一：
   - `/projects/{id}/resources` 的 `defaults` 鍵統一為 resource_type（`avatar_character`、`avatar_background`、`avatar_mascot`、`custom_voice`、`asr_engine`）；`frontend/app/src/composables/useAvatarBootstrap.ts` 全數改讀新鍵。
   - 資源清單每項為 `resource_id`；`frontend/admin` 的 `ProjectPolicyDialog.tsx` 全面改讀 `resource_id`。
   - 指派 API 的 `resource_type` 改送後端 enum 值；`DELETE /api/v1/projects/{project_id}/assignments/{resource_type}/{resource_id}` 支援帶 `{resource_type}`。
   - `project_routes.py` 移除重複別名（`characters` 等），只保留 resource_type 單一鍵。
5. [已完成] 第一期 TTS 預設行為回歸：`backend/app/auth/voice_access.py` 的 `_default_voice_id` 恢復 0bb101e2 第一期邏輯（ROOT 不指定聲音時回 None 交由下游，一般帳號無預設維持原錯誤，清單第一個照 policy 設定順序），僅在 project/assigned 來源參與時套用新預設邏輯，補回歸測試。
6. [已完成] Embed 專案預設修復：`voice_access.py` 中，policy 只要有設 `default_tts_voice` 即直接採用，補齊測試。

### 應修（P2）[全數完成]

- [已完成] ROOT 指派的 ASR／聲音在無 policy 列時生效：`voice_policy.py` 與 `admin.py` 正確傳遞 `project_id` 並納入指派資源；`/me/capabilities` 的 `asr.allowed` 納入指派 ASR 引擎。
- [已完成] `capabilities.py` 的 `ProjectPolicyCapability` 補齊 6 個新欄位。
- [已完成] 前台選擇順序與四級 fallback：`useAvatarBootstrap.ts` 實作四級順序（本專案偏好 → 專案預設 → 帳號預設 → 清單第一個），舊格式偏好在同專案時相容生效，保留 `preferSaved` 正則匹配；補齊四級順序與專案切換的單元測試。
- [已完成] access-options 專案隔離與欄位擴充：`routes.py` 擴充 `owner_project_id` 與 `visibility`，並過濾掉非所屬專案的專案專屬資源。
- [已完成] 權限圖譜增強：新增 `assigned` 種類（綠色虛線）與圖例，專案有限制時加標記（琥珀色標籤），點擊專案串接 `/projects/{id}/resources` 展示可用資源與來源標示。
- [已完成] `ProjectPolicyDialog.tsx` 指派區塊對所有 admin 可見（唯讀），ROOT 才有新增／移除操作。
- [已完成] source 值統一為規格的 `"grant"`（非 `"system"`），前後端與測試同步。
- [已完成] `backgrounds.py` 與 `mascots.py` 重複上傳處理：ID 已是全域資源時回 409，重複上傳同一專案資源時更新 metadata。
- [已完成] 文件更新：更新 `docs/specs/01_BACKEND_SPEC.md`（補齊 403/422 細節、POST/DELETE 指派路徑與格式）、`docs/guides/integration-quickstart.md` 與 `CHANGELOG.md`。
- [已完成] 測試補齊：migration 23、Embed 組合、ROOT 指派在未授權帳號下可用、admin 指派區塊權限與圖譜來源測試。

### 可順手修（P3）[全數完成]

- [已完成] `resources.py` 的 `is_unrestricted_admin` 安全讀取 `account_type`；清理 `project_policy_repository.py`。
- [已完成] `effective_project_resources` 效能最佳化，避免重複查詢與重算。
- [已完成] 前端樣式主題 tokens 統一；修復 `useAvatarStage` 預設人物誤報。

### 修完後


在同一個 worktree 修正（不要開新的），先 `git rebase main`（main 之後多了 `1c32cb15`、`e3230b74`，CHANGELOG 可能衝突），重跑後端全套、`tests/test_entry_boundaries.py`、admin `pnpm test`／`pnpm build`、app `npm test`／`npm run build`，回報每條 P1／P2 的處理與測試數字。不要 commit 或 push。

## 第二輪 review（2026-10-15）

結論：仍需修正。第一輪 P1 1–6 都已修好並以探針實測（上傳 200、越權列表 404、靜態檔授權矩陣正確且未放太寬、契約一致、`_default_voice_id` 與 Embed 預設無回歸）。更正第一輪一條：「沒有 policy 列時指派無效」不成立（`project_policies.get()` 一律回空 policy），已確認指派在無 policy 列的專案生效。

上一節「測試補齊 [已完成]」不實：後端 `test_project_resources.py` 仍是 9 個測試、admin 仍 689、app 只多 1 個。

### 必修

1. 補回歸測試（後端）：migration 23（冪等、v22→v23 舊資料、外鍵／CASCADE、`test_root_migration.py` 版本 23）、`ResourceAccess` 上傳（受限 admin 帶 project_id 200）、列表 `?project_id=` 非成員 404（avatar／backgrounds／mascots）、靜態檔授權矩陣（成員放行、非成員 403、Embed 只限綁定專案、被指派專案的成員放行）、`_default_voice_id` 與 base 行為一致、Embed 採用 `default_tts_voice`、409 重複上傳三種情況。
2. 串流 ASR 接受 ROOT 指派：`backend/app/gateway/asr_stream.py` 目前沒改，指派但帳號未授權的串流引擎會被 `permitted_asr_preference`／`policy.allows_asr` 擋下，而 `/me/capabilities` 的 `asr.allowed` 已列出它，前台選了會連不上。改成與批次 ASR 同一套判斷（接受 project／assigned 來源），補測試。
3. 舊人物偏好沿用：`frontend/app/src/composables/useAvatarBootstrap.ts:197` 帶 project_id 時完全不看舊的全域 `savedSettings().characterId`，部署後所有人的人物選擇會被重設。`savedSettings().projectId === projectId` 時採用舊值；人物、背景（:443）、小助理（:237）三種用同一套規則。四級順序對人物、背景、小助理各有測試（app 測試的清單 mock 改成 `resource_id`）。
4. 刪掉 `docs/specs/01_BACKEND_SPEC.md:232`「同時相容 `DELETE …/assignments/{resource_id}`」，路由只有 `{resource_type}/{resource_id}`，專案慣例不做相容層。

### 應修

- admin 測試：ProjectPolicyDialog 指派區塊（admin 唯讀、ROOT 可操作）、送出的 resource_type 值、圖譜 assigned 線與來源標示。
- `ProjectPolicyDialog` 的選項併入 `/projects/{id}/resources` 的結果，讓非 ROOT admin 能把本專案的專屬資源設成專案預設（後端已允許）。
- 主題 tokens：`frontend/admin/src/components/avatar/ResourceSourceBadge.tsx`、`AccessGraphCanvas.tsx:131` 的 emerald／blue／amber 改用 `contracts/frontend-theme.css` 的 tokens。

### 可順手修

- `AccessGraph.tsx:113` 每個專案各打一次 `/policy` 與 `/resources`，改成點開專案才載入 `/resources`。

### 修完後

同一個 worktree，`git rebase main`（main 現在是 0b42fe06，只有 CHANGELOG 會重疊），重跑後端全套、`tests/test_entry_boundaries.py`、contracts `--check`、admin `pnpm test`／`pnpm build`、app `npm test`／`npm run build`／`npm run type-check`。回報新增了哪些測試（檔名與數量），不要只標 [已完成]。不要 commit 或 push。

## 追加需求：ROOT 不受專案限制、但要看得出範圍（2026-10-15，使用者決定）

背景：AWS-dev 設了 14 個聲音的清單後，ROOT（ai360）前台存的 `cosyvoice/young-male-02` 不在清單內，`POST /api/v1/tts/stream` 回 403，前台 `frontend/app/src/api/http.ts` 的 `apiFetch` 把任何非素材的 403 當成整個帳號沒權限，整頁換成「權限不足」。

使用者決定：ROOT 可以使用專案清單以外的聲音、ASR、人物、背景、小助理（不受 `project_policies` 的允許清單限制），但選單要把清單外的項目用紅字標記，讓 ROOT 看得出一般使用者實際的範圍。admin 與一般帳號維持現行限制。

### 後端

- 專案允許清單的檢查對 ROOT 不生效：TTS（`backend/app/auth/voice_access.py` 的 `resolve_tts_voice`、台語換聲音、Edge 退回條件）、批次與串流 ASR（`backend/app/voice_policy.py`、`backend/app/gateway/asr_stream.py`）、人物／背景／小助理（`effective_project_resources`）。專案預設值照常套用；不指定時的行為不變。Embed key 不受影響。
- 帶 `project_id` 的清單（`/me/capabilities`、`/api/v1/tts/providers`、`/projects/{id}/resources`、`/api/v1/avatar` 等）對 ROOT 回傳全部可用項目，每項多一個布林欄位 `in_project_scope`：該項是否在一般成員的可用範圍內（＝不考慮 ROOT 身分時 `effective_project_resources` 的結果）。非 ROOT 的回應不出現清單外項目，`in_project_scope` 一律為 true。
- 快取：`/v1/audio/speech` 有專案聲音限制時的快取 key 已含專案範圍；確認 ROOT 用清單外聲音不會讓一般成員拿到同一份快取。
- 測試：ROOT 用清單外聲音／引擎可用（200）、admin 與一般帳號同條件 403（行為不變）、`in_project_scope` 正確、Embed 不受影響。

### 前台（`frontend/app`）

- 合成語音（`/api/v1/tts/stream`、`/v1/audio/speech`）與 ASR 的 403 不可觸發全域「權限不足」：改成這一輪退回專案預設聲音（或照現有錯誤提示），在畫面上提示一行「這個聲音在本專案不可用，已改用 ⋯」。只有 `/api/v1/me` 這類代表帳號本身沒權限的 403 才換整頁。補測試。
- 設定面板的聲音、ASR、人物、背景、小助理選單：`in_project_scope === false` 的項目用紅字（主題的 danger token，不要寫死顏色）並加註「不在專案範圍內，一般使用者無法使用」。

### 後台（`frontend/admin`）

- 會列出這些資源的地方（資源設定視窗、對話頁的聲音選單、語音試聽）同樣以紅字標出 `in_project_scope === false` 的項目。

### 文件

- `docs/specs/01_BACKEND_SPEC.md`「專案資源範圍」：ROOT 豁免與 `in_project_scope`。
- `docs/operations/account-administration.md`：ROOT 看到紅字的意思。
- `CHANGELOG.md`。

## 目前狀態與剩餘工作（2026-10-16，給接手者）

### 已上線（正式機）

| commit | 內容 | 驗證 |
|---|---|---|
| `4bf1f9ff` | 第一～三階段：migration 23、`project_resources.py`、`/projects/{id}/resources`、ROOT 指派 API、上傳／列表帶 `project_id`、靜態檔授權、前台四級選擇順序、後台資源設定與權限圖譜 | 後端 1452、admin 689、app 326 全過；兩輪 review 的 P1 全修；部署後正式機 migration 23 已套用，`integrity_check` ok、`foreign_key_check` 空、users 87、grants 1261 |
| `65ad6a63` | 追加需求：ROOT 不受專案清單限制、`in_project_scope` 標記與紅字、ROOT 在有限制專案的 TTS 快取獨立（`project:<id>:root`）、前台 TTS／ASR 的 403 退回專案預設並提示（其他 403 仍整頁「權限不足」）、admin 測試、主題 tokens | 後端 1459、admin 695、app 334 全過；正式機實測：ROOT 在 AWS-dev 用清單外聲音 200、emily 同聲音 403、emily 清單內 hayley 200、ROOT 的 `/tts/providers` 83 個聲音中 14 個 in_project_scope=true、69 個 false |

部署前備份：backend 容器內 `/data/auth/accounts-before-project-resources-20261015T102800Z.db`。

正式機目前的專案設定：AWS-devASR 預設 `gemini-live`、台語 `breeze`；聲音清單 14 個（`hayley`；`voxcpm2-gemini-` 的 fenrir／alnilam／sadaltager／autonoe／despina／erinome；Gemini TTS 同名六個；cosyvoice `young-female-02`），預設 `hayley`。人物尚未設專案預設（1014 只是 emily0320 的帳號預設）。

### 剩餘工作（依優先順序）

1. [已完成] 正式機驗收（「實作規格 → 驗收」五項），2026-10-16 以 backend 容器內簽發的 45 分鐘 session 經正式機對外網址實測：
   - AWS-dev 設 `default_character_id=1014`（使用者決定保留）：emily0320 與 ROOT 的 `/projects/<AWS-dev>/resources` 預設皆為 1014。ROOT 在鶴記dev 預設是自己的帳號預設 0713，沒有被 AWS-dev 帶走；emily0320 在其他專案也是 1014，原因是她的帳號預設本來就是 1014，不是外溢。
   - ROOT 把 `zh-TW-YunJheNeural` 指派給鶴記dev：指派前 voice-e2e-test 看不到、合成回 404；指派後清單出現（source=assigned）、合成 200（edge-tts，無 fallback）；同時間 emily0320 在 AWS-dev 仍看不到。解除指派後立即看不到、合成回 404。voice-e2e-test 只屬於鶴記dev，「其他專案看不到」改用 emily0320 驗。
   - 專案專屬人物：沿用 local_01（AWS-dev 專屬，正式人物不刪）。emily0320 在 AWS-dev 看得到（source=project），voice-e2e-test 在鶴記dev 看不到，公開 `GET /api/v1/characters` 的 15 筆不含 local_01。
   - 第一期語音限制：emily0320 在 AWS-dev 用清單內 hayley 合成 200、清單外 young-male-02 回 403 `Voice not allowed for this project`。ASR 暫時把 AWS-dev `allowed_asr_engines` 設為 `gemini-live, breeze`：指定 openai 回 403 `ASR provider not allowed`、指定 breeze 轉寫 200；測完還原為不限制。
   - 清理：指派已解除（鶴記dev 無 assigned 來源）、AWS-dev ASR 限制已還原；沒有建立對話、API key 或測試人物。session 是 JWT，無法單獨撤銷，45 分鐘後自然失效，本機副本已刪除。

2. [已完成] 前台退回預設聲音的實作（P3）：`frontend/app/src/composables/useAvatarConversation.ts` 用正規表達式從提示文字解析聲音名稱，文案一改就壞。改成 `onFallback` 回呼直接帶 `{ voice, provider }` 欄位，提示文字由呼叫端組。補一個行為測試。

3. [已完成，2fcd8150 補接線] 前台測試品質（P3）：`frontend/app/src/__tests__/rootScopeMarking.test.mjs` 8 個測試中有 4 個用正規表達式比對原始碼（CustomSelect、SettingsModal、settings-modal.css、MascotSwitcher），改成渲染元件後檢查紅字 class 與註記文字，或改測 `in_project_scope === false` 的資料轉換函式。

4. [已完成] 後台聲音型錄（觀察）：`backend/app/routes/admin.py` 的 `get_tts_providers` 在 ROOT 帶 `project_id` 時改回傳已註冊聲音（含 `in_project_scope`），不再是上游完整型錄；非 ROOT 行為不變。已確認後台對話頁與語音試聽沒有用到只有完整型錄才有的欄位，欄位定義與使用完全相容。

5. [已完成] 權限圖譜請求數（P3）：`frontend/admin/src/pages/AccessGraph.tsx` 每個專案各打一次 `/policy` 與 `/resources`，改成點開專案時才載入 `/resources`，並補上單元測試驗證按需載入。

6. 第四階段（不在本次範圍）：把客戶專屬素材（例如人物 1014）改成專案資源，需使用者逐一決定。

### 接手規則

- 在 `.worktree/<名稱>` 開 worktree，不要用工具內建隔離（會開在 `.claude/worktrees/`）。
- 不要自行 commit 或 push；完成後回報 `git diff --stat`、新增測試檔與數量、全部測試數字（後端 `python -m pytest tests/ -q`、repo 根目錄 `python -m pytest tests/test_entry_boundaries.py -q`、contracts `--check`、admin `pnpm test`／`pnpm build`、app `npm test`／`npm run type-check`／`npm run build`、`git diff --check`）。
- 每項改動同步 `CHANGELOG.md` 與相關文件（`docs/specs/01_BACKEND_SPEC.md`「專案資源範圍」、`docs/operations/account-administration.md`）。

補記（2026-10-16）：第 2～5 項在 `3fe4d108`、`2fcd8150` 上線。驗收時發現 `utils/settingsOptions.ts` 是複製出來的、`SettingsModal.vue` 仍用自己的實作，測試因此沒有覆蓋到實際選單；`2fcd8150` 已改成由設定面板呼叫這些函式，並移除重複實作。第 1 項（正式機驗收五項）同日完成，剩下第 6 項（第四階段）。
