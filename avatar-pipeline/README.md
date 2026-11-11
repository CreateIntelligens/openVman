# avatar-pipeline

把一段正面說話的影片（或一張正面人像圖）轉成虛擬人前台能載入的素材包。backend 收上傳、排工作，
這個容器一次跑一件，產物直接寫回共用的 `/data`，轉完 backend 再把它登錄成角色。

## 素材包格式

每個角色在 `data/avatar/<char_id>/` 有三個檔案：

| 檔案 | 內容 |
|---|---|
| `01.webm` | VP9、25 fps、無聲；來源有透明通道時輸出 `yuva420p`（WebM `alpha_mode=1`），否則 `yuv420p`。右上角 4×4 像素是幀同步標記，灰階值 `(frame % 7) * 40`，透明素材上也強制不透明，前台 runtime 靠它從畫面反推幀序 |
| `combined_data.json.gz` | 保留上傳 API 的既有檔名，內容僅為 `{ "render_data": <v2 payload> }`，不夾帶共用模板、舊姿態資料或加密資料 |
| `render_data.json.gz` | 同一份 `openvman.render.v2` gzip JSON，供瀏覽器直接載入 |

預設產製不讀取 `face_template.json`、歷史校準 profile、抽出的網格、形變基底或牙齒圖集。
每幀透過 MediaPipe FaceMesh 量測人物影片的嘴唇：`region` 是原影片的浮點裁切框
`[left, top, right, bottom]`，`outer`／`inner` 各為依環排列的 20 組 xy，轉為裁切框內
180 × 180 座標（各 40 個數字）。保留浮點位置，不套用舊版向下取整或模板仿射配準。
網格、嘴型位移、牙齒著色及融合範圍由前端程序產生，並非本檔案內藏的抽取資料。

`provenance` 記錄實際 `01.webm` 的 SHA-256、產製模組雜湊、MediaPipe 版本與三個
TFLite 模型雜湊。MediaPipe 及其偵測模型仍是第三方依賴；不宣稱整條管線完全自研。
全畫面 FaceMesh 失敗時，才用官方長距離 FaceDetection（`model_selection=1`）定位臉，
將量測框放大為 1.5 倍正方 ROI 後跑局部 FaceMesh，後續依量測點更新 ROI；
定位或局部追蹤仍失敗、座標非有限、嘴部超出裁切時，整件失敗，不使用舊模板備援。
`provenance.tracking` 記錄全畫面／ROI 幀數與重新定位次數，模型清冊包含官方長距離模型。
JSON 在完整序列化後設定 `0644` 並原子寫入，供不同服務使用者讀取；
獨立 sidecar 的 gzip timestamp 固定為 0，支援重現比對。

## 處理流程

1. `ffmpeg` 轉成 25 fps、最長邊 1920 以內、每幀都是關鍵幀的 FFV1 BGRA 中繼檔（無損、保留透明）。
   OpenCV 讀不到透明通道，之後每一步都經 ffmpeg rawvideo 管線讀幀。
2. 首尾銜接（`loop`）：比較第一幀與最後一幀縮圖的平均灰階差，超過門檻就在後面接上倒放片段
   （`0…n-1` 再 `n-2…1`），循環播放時回到第 0 幀不會跳。
3. 邊打幀同步標記邊轉 VP9（`-auto-alt-ref 0`，隱藏參考幀會讓幀序對不上）。
4. 在最終 `01.webm` 上以 MediaPipe FaceMesh 逐幀直接量測嘴唇，信心門檻 0.5，
   使用 468 點模型、不啟用虹膜細化；不讀歷史偵測校準或共用模板。
5. 以嘴寬的 2.4 倍建立正方嘴部範圍，平移裁切框以保持在影片內；保留浮點座標。
6. 寫入含來源清冊的 v2 sidecar 與同內容上傳包；不再生成舊引擎姿態或加密模板。

單一 ffmpeg 步驟超過 900 秒就中止並回報失敗。

## 輸入

| 類型 | 副檔名 | 處理 |
|---|---|---|
| 影片 | `.mp4`、`.mov`、`.webm` 等 ffmpeg 讀得到的格式 | 音軌丟棄；VP8／VP9 WebM 帶 `alpha_mode=1` 時改用 libvpx 解碼，ffmpeg 內建解碼器會忽略透明通道 |
| 圖片 | `.png`、`.jpg`、`.jpeg`、`.webp` | 解碼一次後複製成 10 秒（250 幀）的靜止片段；PNG／WebP 的透明通道保留 |

圖片只解碼一次再用 `loop` 濾鏡複製，不用 `-loop 1` 反覆讀檔：帶 C2PA 簽章或 IEND 後有多餘位元組的 PNG
（AI 生成圖常見）在 `-loop 1` 下解不出下一幀，會一直卡住。

首尾銜接由 `--loop` 控制：`auto`（預設）只在首尾差超過 `--seam-threshold`（預設 6.0，0–255 灰階）時接倒放，
`always` 一律接，`off` 不接。靜止圖片首尾相同，不會接。

`pipeline/video_lips.py` 是預設新產製入口，其輸入僅為人物影片、MediaPipe 及本專案
的嘴部裁切／座標轉換公式。偵測使用 Dockerfile 鎖定的 MediaPipe `0.10.14`，無備援模型。
透明 VP9 影片本身仍保留 alpha；偵測明確以 libvpx 解碼 alpha，再鋪中性灰底，
避免 ffmpeg 原生 WebM 解碼器忽略透明平面。

`geometry.py`、`landmarks.py`、`profiles/legacy_dh_live.json`、共用模板及 bundle 的舊版
加密／姿態函式暫留給歷史資料與遷移測試，預設 builder 不匯入或使用它們。
歷史來源揭露仍保留，不能把舊角色的 v1 sidecar 改版本名稱當成重新產製。

## 設定

複製 `.env.example` 成 `avatar-pipeline/.env`：

| 變數 | 說明 |
|---|---|
| `AVATAR_BUNDLE_KEY` | 僅歷史 v1 素材包解密／轉換需要；新 v2 產製不需要金鑰。部署後不要更換既有金鑰，以免無法讀取舊包 |
| `AVATAR_PIPELINE_JOB_TIMEOUT` | 單件上限秒數，預設 1800 |
| `REDIS_URL` | 由 compose 注入 |

## 佇列契約

- 佇列名稱 `vman:avatar-pipeline`，函式 `build_avatar_bundle`，payload `{"job_id", "input_path", "output_dir"}`。
- 狀態寫在 Redis `vman:avatar-pipeline:job:<job_id>`（24 小時），欄位 `state`（queued／running／done／failed）、`stage`、`done`、`total`、`error`、`frame_count`、`width`、`height`。backend 的 `app/avatar/jobs.py` 用同一把 key，改欄位要兩邊一起改。
- 一次只跑一件（`max_jobs = 1`），不重試；逾時或 MediaPipe 當掉只影響那一件。

## 手動使用

```bash
docker compose exec avatar-pipeline \
  python -m pipeline.cli --input /data/avatar-jobs/clip.mp4 --output /data/avatar-jobs/out
```

完成時最後一行是 JSON，含 `frame_count`、`width`、`height`、`alpha`（是否保留透明）、
`seam_difference`（首尾差）、`ping_pong`（是否接了倒放）。

產出的 `01.webm`、`combined_data.json.gz` 與 `render_data.json.gz` 一起放入 `data/avatar/<char_id>/` 並在後台登錄即可；
或直接在管理後台「虛擬人 → 從影片或圖片產生人物」上傳，backend 會自動排程與登錄。

既有影片可只重建 v2 幾何，保留影片 bytes 不變：

```bash
docker compose exec avatar-pipeline \
  python -m pipeline.video_lips --video /data/avatar/<id>/01.webm \
  --output /data/avatar-jobs/rebuilt/render_data.json.gz
```

工具只有 `--video`、`--output` 兩個必填參數，輸出為 gzip JSON；不用帳號或網路服務，
僅處理容器可讀的檔案。請輸出到獨立路徑驗收，避免覆寫已發布角色。任一錯誤非零退出。

## 既有素材包轉換（歷史 v1 工具）

既有人物缺少 sidecar 時，Backend 在資源授權檢查通過後，可用同一把 `AVATAR_BUNDLE_KEY`
解密原 `combined_data.json.gz`，以 ffprobe 取得影片尺寸並原子新增 sidecar；缺金鑰或資料無效會
回應 HTTP 409 提示重新產製，不載入舊 runtime 備援。上傳的新包則直接驗證並取出外層 `render_data`。

管理者也可在已配置相同金鑰的產製容器批次轉換：

```bash
docker compose exec avatar-pipeline \
  python -m pipeline.render_data --directory /data/avatar
```

預設略過已存在的 sidecar；只有明確加上 `--overwrite` 才重建。轉換只新增／更新
`render_data.json.gz`，保留原 `01.webm` 與 `combined_data.json.gz`，不把轉換結果寫回舊包。
CLI 最後列出成功與失敗項目，有失敗時以非零狀態結束；不需啟動瀏覽器或讀取舊 runtime 的 heap。

## 測試

```bash
docker build -t openvman-avatar-pipeline:dev avatar-pipeline
docker run --rm -v "$PWD/avatar-pipeline/tests:/app/tests:ro" \
  -v "$PWD/avatar-pipeline/pytest.ini:/app/pytest.ini:ro" \
  openvman-avatar-pipeline:dev sh -c "pip install -q pytest && python -m pytest -q"
```

`tests/test_geometry.py` 覆蓋歷史裁切校準、任意尾端維度的平滑與座標／邊界驗證；
`tests/test_landmarks.py` 用介接替身檢查 RGB、信心門檻、中央重試座標、478 點深度契約與資源回收，
不把替身測試當成實際模型推論驗收。`tests/test_render_data.py` 檢查 row-vector 仿射、950 值排列、
數值／維度／空裁切驗證、gzip 原子發布，以及預設 builder 不碰舊模板、加密或姿態函式，sidecar 與包內 v2 欄位完全一致。
`tests/test_video_lips.py` 驗證浮點位置可逆、裁切邊界、退化／非有限輸入拒絕、可重現 gzip
及輸入來源清冊。
完整測試另外涵蓋 ffmpeg、透明通道、同步標記及 bundle 形狀。

測試不需要 MediaPipe 模型以外的外部資源；根目錄的 `pytest.ini` 排除本目錄，
因為主機與 CI 的精簡環境沒有 mediapipe。
