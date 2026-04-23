## Why

目前 backend metrics 僅存於 process 記憶體，服務重啟即歸零（VH-131），且沒有標準格式輸出，無法接外部監控工具。`docs/01_BACKEND_SPEC.md` 第 12 節明確要求暴露指標供 Prometheus / Grafana 收集，現在 staging 硬化階段需要落實。

## What Changes

- `docker-compose.yml` 新增 `prometheus` 和 `grafana` 兩個 service
- `infra/prometheus/prometheus.yml` 設定 scrape 目標（backend + brain）
- `infra/grafana/provisioning/` 設定 datasource 自動掛載
- backend 新增 `/metrics/prometheus` endpoint，輸出 Prometheus text format（使用 `prometheus_client`）
- 指標命名對齊 spec：`vman_ttfb_ms`、`vman_tts_latency_ms`、`vman_active_sessions`、`vman_error_total` 等
- frontend admin 新增「監控」頁面，以 iframe embed Grafana dashboard

## Capabilities

### New Capabilities

- `observability-prometheus-export`: backend 輸出 Prometheus text format metrics endpoint，指標命名對齊 BACKEND_SPEC 第 12 節
- `observability-dashboard`: Prometheus + Grafana 容器化部署，Grafana datasource 自動 provision，admin 前端 embed dashboard

### Modified Capabilities

- `live-voice-websocket-pipeline`: 新增 WS disconnect/reconnect/error counter（已部分實作於 VH-128/VH-132）

## Impact

- **新依賴**: `prometheus_client` Python 套件（backend）
- **新容器**: prometheus, grafana（各需少量 CPU/記憶體，無 GPU）
- **新檔案**: `infra/prometheus/prometheus.yml`, `infra/grafana/provisioning/datasources/prometheus.yaml`
- **API**: 新增 `GET /metrics/prometheus`（Prometheus text format）
- **前端**: admin 新增監控頁路由
- **不影響**: 現有 `GET /metrics` JSON endpoint 保持不變（向後相容）
