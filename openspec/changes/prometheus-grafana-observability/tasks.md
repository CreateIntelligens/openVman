## 1. Backend — Prometheus metrics bridge

- [x] 1.1 在 `backend/requirements.txt`（或 pyproject.toml）加入 `prometheus_client`
- [x] 1.2 在 `backend/app/observability.py` 建立 `prometheus_client` registry：定義 `vman_ttfb_ms` Histogram、`vman_tts_latency_ms` Histogram、`vman_active_sessions` Gauge、`vman_error_total` Counter、`http_requests_total` Counter、`live_ws_disconnect_total` Counter、`live_ws_errors_total` Counter、`live_ws_reconnect_total` Counter
- [x] 1.3 在 `record_timing`、`increment_counter`、`set_active_sessions` 等 helper 裡加 bridge 呼叫，同步更新 prometheus_client metrics
- [x] 1.4 在 `backend/app/routes/admin.py` 新增 `GET /metrics/prometheus`，用 `generate_latest()` 輸出 text format，Content-Type 設為 `text/plain; version=0.0.4`
- [x] 1.5 驗證：`curl http://localhost:8200/metrics/prometheus` 能看到 `vman_` 開頭的指標，且原 `GET /metrics` JSON 不受影響

## 2. Infra 設定檔

- [x] 2.1 建立 `infra/prometheus/prometheus.yml`，設定 scrape backend:8000 `/metrics/prometheus`，scrape interval 15s，retention 30d
- [x] 2.2 建立 `infra/grafana/provisioning/datasources/prometheus.yaml`，設定 Prometheus datasource 自動掛載
- [x] 2.3 建立 `infra/.env.example`，加入 `GRAFANA_PASSWORD=` 說明

## 3. Docker Compose

- [x] 3.1 在 `docker-compose.yml` 加入 `prometheus` service（image: prom/prometheus:v2.52.0，掛 infra/prometheus/prometheus.yml，volume: prometheus-data）
- [x] 3.2 在 `docker-compose.yml` 加入 `grafana` service（image: grafana/grafana:10.4.2，掛 provisioning 目錄，volume: grafana-data，env: GRAFANA_PASSWORD、sub-path 設定）
- [x] 3.3 在 `volumes:` 區塊加入 `prometheus-data` 和 `grafana-data`

## 4. Nginx 反向代理

- [x] 4.1 在 admin nginx 設定（`frontend/admin/nginx/`）加入 `/grafana/` location block，proxy 到 `http://grafana:3000`
- [x] 4.2 `/grafana/` location 加 websocket upgrade（supports Grafana Live `/api/live/ws`）

## 5. Admin 前端監控頁

- [x] 5.1 新增監控頁路由（路徑 `/monitoring` 或 `/monitor`）
- [x] 5.2 實作監控頁元件：iframe 指向 `/grafana/`，寬高填滿可視區域
- [x] 5.3 在 admin 側邊欄或導覽列加入「監控」入口

## 6. Grafana 設定與 provisioning

- [x] 6.1 建立 `infra/grafana/grafana.ini`，集中管理 server/security/auth.anonymous/news 等設定（取代 compose 中的 `GF_*` env 變數）
- [x] 6.2 docker-compose.yml 掛載 `grafana.ini` 為 `/etc/grafana/grafana.ini:ro`，compose 只保留 `GF_SECURITY_ADMIN_PASSWORD` env
- [x] 6.3 開啟 iframe 嵌入（`security.allow_embedding=true`）、匿名 Viewer（`auth.anonymous.enabled=true`、`org_role=Viewer`）、關閉 News feed（`news.news_feed_enabled=false`）

## 7. Dashboard provisioning（完整版）

- [x] 7.1 建立 `infra/grafana/provisioning/dashboards/dashboards.yaml`，註冊 dashboard provider（path 指向 `/etc/grafana/dashboards`）
- [x] 7.2 docker-compose.yml 的 grafana service 掛載 `./infra/grafana/dashboards:/etc/grafana/dashboards:ro`
- [x] 7.3 建立 `infra/grafana/dashboards/vman-overview.json`，內容涵蓋：
      - 概覽列（Stat）：`vman_active_sessions`、總 QPS（`sum(rate(http_requests_total[5m]))`）、錯誤率（`sum(rate(vman_error_total[5m]))` / QPS）、總錯誤數
      - TTFB p50/p95/p99（Time series，用 `histogram_quantile` 對 `vman_ttfb_ms_bucket`）
      - TTS latency p50/p95/p99（同上，對 `vman_tts_latency_ms_bucket`）
      - HTTP 請求（Time series，by method/status）：`sum by (status) (rate(http_requests_total[5m]))`
      - WebSocket 事件（Time series）：`rate(live_ws_disconnect_total[5m])`、`rate(live_ws_errors_total[5m])`、`rate(live_ws_reconnect_total[5m])`
      - Dashboard `uid` 固定為 `vman-overview`、標題 `VMAN Overview`、預設 time range `now-1h`、refresh `10s`
- [x] 7.4 修改 `frontend/admin/src/pages/Monitoring.tsx`，iframe `src` 改為 `/grafana/d/vman-overview/vman-overview?kiosk=tv&refresh=10s`（`kiosk=tv` 隱藏 Grafana chrome、保留 viewer 控制）

## 8. 驗證

- [x] 8.1 `docker compose up -d prometheus grafana` 啟動，確認兩個容器健康
- [x] 8.2 Prometheus UI（透過 container 內部）能看到 backend scrape target 為 UP
- [x] 8.3 Grafana UI 透過 `/grafana/` 能正常載入，Prometheus datasource 已自動掛載
- [x] 8.4 admin 前端監控頁 iframe 顯示 VMAN Overview dashboard，面板有資料、無 News panel、無 moment.js deprecation warning
- [x] 8.5 重啟 backend 後，Prometheus 歷史資料仍存在（VH-131 驗收）

## 9. Brain service Prometheus metrics

- [x] 9.1 `brain/api/requirements.txt` 加入 `prometheus_client`
- [x] 9.2 `brain/api/safety/observability.py` 新增 `render_prometheus()` helper，將 MetricsStore snapshot 轉為 Prometheus text exposition format（counters → counter，timings → `_count`/`_sum`/`_max`）
- [x] 9.3 `brain/api/routes/health.py` 新增 `GET /brain/metrics/prometheus`，回傳 text format
- [x] 9.4 `infra/prometheus/prometheus.yml` 的 brain job `metrics_path` 改為 `/brain/metrics/prometheus`
- [x] 9.5 驗證：`docker exec openvman-prometheus-1 wget -qO- http://localhost:9090/api/v1/targets` 顯示 backend 與 brain 兩個 target 都是 `up`
