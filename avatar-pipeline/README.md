# avatar-pipeline

把一段正面說話的影片（或一張正面人像圖）轉成虛擬人前台能載入的素材包。backend 收上傳、排工作，
這個容器一次跑一件，產物直接寫回共用的 `/data`，轉完 backend 再把它登錄成角色。

## 素材包格式

每個角色在 `data/avatar/<char_id>/` 有兩個檔案：

| 檔案 | 內容 |
|---|---|
| `01.webm` | VP9、25 fps、無聲；來源有透明通道時輸出 `yuva420p`（WebM `alpha_mode=1`），否則 `yuv420p`。右上角 4×4 像素是幀同步標記，灰階值 `(frame % 7) * 40`，透明素材上也強制不透明，前台 runtime 靠它從畫面反推幀序 |
| `combined_data.json.gz` | `json_data`：每幀一列，16 個姿態矩陣值接 209 個變形點的 (x, y)，座標在 180 方格內；`combined_data`：Base64(IV ‖ AES-128-CBC(內層 JSON))，內層有共用的臉部模板（465 點）、每幀嘴部裁切框、幀數 |

內層 JSON 的 `uid` 以 `vman_` 開頭。姿態矩陣是模板前 209 點到該幀標準化變形點的最小平方仿射解，
所以模板不必貼合每個人的臉，矩陣會吸收差異。

## 處理流程

1. `ffmpeg` 轉成 25 fps、最長邊 1920 以內、每幀都是關鍵幀的 FFV1 BGRA 中繼檔（無損、保留透明）。
   OpenCV 讀不到透明通道，之後每一步都經 ffmpeg rawvideo 管線讀幀。
2. 首尾銜接（`loop`）：比較第一幀與最後一幀縮圖的平均灰階差，超過門檻就在後面接上倒放片段
   （`0…n-1` 再 `n-2…1`），循環播放時回到第 0 幀不會跳。
3. MediaPipe Face Mesh 逐幀取 478 個 3D 特徵點；透明像素先鋪成中性灰再偵測。第一幀要是單一正臉，臉至少 80×80 像素。
4. 邊打幀同步標記邊轉 VP9（`-auto-alt-ref 0`，隱藏參考幀會讓幀序對不上）。
5. 特徵點、裁切框中心、姿態矩陣各做一次對稱 5 幀平滑（零相位，不產生延遲）。
6. 加密、gzip、寫檔。

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

特徵點與幾何函式移植自 [DH_live](https://github.com/kleinlee/DH_live)（MIT），去掉 torch 路徑。

## 設定

複製 `.env.example` 成 `avatar-pipeline/.env`：

| 變數 | 說明 |
|---|---|
| `AVATAR_BUNDLE_KEY` | 16 個 ASCII 字元的加密金鑰，必填；前台 runtime 用同一把解密，部署後不要換 |
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

產出的 `01.webm` 與 `combined_data.json.gz` 複製到 `data/avatar/<char_id>/` 並在後台登錄即可；
或直接在管理後台「虛擬人 → 從影片或圖片產生人物」上傳，backend 會自動排程與登錄。

## 測試

```bash
docker build -t openvman-avatar-pipeline:dev avatar-pipeline
docker run --rm -v "$PWD/avatar-pipeline/tests:/app/tests:ro" \
  -v "$PWD/avatar-pipeline/pytest.ini:/app/pytest.ini:ro" \
  openvman-avatar-pipeline:dev sh -c "pip install -q pytest && python -m pytest -q"
```

測試不需要 MediaPipe 模型以外的外部資源；根目錄的 `pytest.ini` 排除本目錄，
因為主機與 CI 的精簡環境沒有 mediapipe。
