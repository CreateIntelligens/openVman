# Backend

FastAPI 服務處理帳號與專案授權、角色素材儲存、對話及媒體工作排程；架構與啟動方式見根目錄 README。

## 角色 CPU 渲染資料

`GET /static/characters/{char_id}/render_data.json.gz` 使用與原始影片／素材包相同的角色資源授權。
公開角色允許匿名讀取；私有、專案或嵌入金鑰授權沿用既有規則。所有檔案路徑限制在該角色目錄，
跨角色的 `../` 與指向其他角色的符號連結會被拒絕。私有回應使用 `Cache-Control: private, no-store`。

回應為 gzip JSON：

| 欄位 | 契約 |
|---|---|
| `schema` | 新版 `openvman.render.v2`；歷史v1僅相容保留 |
| `frameRate` | `25` |
| `frameSize` | `[width, height]`，正整數，單邊至多8192 |
| `geometrySource` | v2固定 `mediapipe-video` |
| `frames` | 非空、最多100000幀；每幀region為影片內有效xyxy，outer／inner各40個0～180有限數值；選用 `eyeSpan` 為1～720的有限數值 |
| `provenance` | 有界白名單來源欄位；接受資料不代表已驗證產製來源 |

v2不含原模板／姿態或抽出rig。新引擎只讀v2；Backend為既有資料保留的v1驗證／離線轉換不代表v1可由新引擎播放，既有角色需從影片重新產製。授權邊界與原始資料不因格式升級而改變。

管理後台上傳的 `combined_data.json.gz` 外層若有 `render_data`，Backend 會驗證它並在角色的
暫存目錄建立 `render_data.json.gz`，與原影片及素材包一起原子發布。影片產製工作也經過相同儲存流程。
合法舊包仍可上傳；損壞 gzip／JSON 或不符契約的新資料回應 HTTP 422，不留下半成品角色。

既有角色缺少 sidecar 時，只有通過資源授權的讀取才會觸發伺服器轉換：

1. 讀取既有 `combined_data.json.gz`，以 `AVATAR_BUNDLE_KEY` 解密 AES-128-CBC 內層的嘴框及模板。
2. `ffprobe` 在 15 秒內取得現有 `01.webm` 尺寸。
3. 以純 Python 計算稠密點並原子建立 sidecar；原始影片與素材包的內容及修改時間不變。

Backend 需配置與 avatar-pipeline 相同的 `AVATAR_BUNDLE_KEY`（16 個 ASCII 字元）。v2新產製包只有明文
`render_data`，不需此金鑰；舊金鑰僅用於歷史包解密，不能以v1自動轉換宣稱資料已獨立。缺金鑰、原包損壞、維度錯誤或無法探測影片時回應 HTTP 409，
提示重新產製；不回退到舊 runtime，錯誤訊息不包含金鑰或私有人物資料。

檔案讀取、gzip 解壓結果及新 sidecar 的未壓縮 JSON 都受到 `AVATAR_MAX_UPLOAD_BYTES` 限制
（預設 100 MiB）；拒絕 NaN、Infinity、空幀及反向裁切框。同步建立相同角色 sidecar 仍只會發布完整檔案。

## 測試

在已安裝 Backend 相依的環境執行：

```bash
cd backend
python -m pytest tests/avatar/ -q
```

`tests/avatar/test_render_data.py` 覆蓋伺服器轉換、來源檔案保持不變、角色授權、跨角色路徑、
缺金鑰、上傳原子發布、數值與大小限制及同時寫入。它使用合成素材與 ffprobe 替身，實際部署後的
影片探測與正式角色載入仍需由整合驗收確認。
