# avatar-pipeline

把一段無聲、正面說話的影片轉成虛擬人前台能載入的素材包。backend 收上傳、排工作，
這個容器一次跑一件，產物直接寫回共用的 `/data`，轉完 backend 再把它登錄成角色。

## 素材包格式

每個角色在 `data/avatar/<char_id>/` 有兩個檔案：

| 檔案 | 內容 |
|---|---|
| `01.webm` | VP9、25 fps、無聲；右上角 4×4 像素是幀同步標記，灰階值 `(frame % 7) * 40`，前台 runtime 靠它從畫面反推幀序 |
| `combined_data.json.gz` | `json_data`：每幀一列，16 個姿態矩陣值接 209 個變形點的 (x, y)，座標在 180 方格內；`combined_data`：Base64(IV ‖ AES-128-CBC(內層 JSON))，內層有共用的臉部模板（465 點）、每幀嘴部裁切框、幀數 |

內層 JSON 的 `uid` 以 `vman_` 開頭。姿態矩陣是模板前 209 點到該幀標準化變形點的最小平方仿射解，
所以模板不必貼合每個人的臉，矩陣會吸收差異。

## 處理流程

1. `ffmpeg` 轉成 25 fps、最長邊 1920 以內的無聲中繼檔。
2. MediaPipe Face Mesh 逐幀取 478 個 3D 特徵點；第一幀要是單一正臉，臉至少 80×80 像素。
3. 邊打幀同步標記邊轉 VP9（`-auto-alt-ref 0`，隱藏參考幀會讓幀序對不上）。
4. 特徵點、裁切框中心、姿態矩陣各做一次對稱 5 幀平滑（零相位，不產生延遲）。
5. 加密、gzip、寫檔。

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

產出的 `01.webm` 與 `combined_data.json.gz` 複製到 `data/avatar/<char_id>/` 並在後台登錄即可；
或直接在管理後台「虛擬人 → 從影片產生」上傳，backend 會自動排程與登錄。

## 測試

```bash
docker build -t openvman-avatar-pipeline:dev avatar-pipeline
docker run --rm -v "$PWD/avatar-pipeline/tests:/app/tests:ro" \
  -v "$PWD/avatar-pipeline/pytest.ini:/app/pytest.ini:ro" \
  openvman-avatar-pipeline:dev sh -c "pip install -q pytest && python -m pytest -q"
```

測試不需要 MediaPipe 模型以外的外部資源；根目錄的 `pytest.ini` 排除本目錄，
因為主機與 CI 的精簡環境沒有 mediapipe。
