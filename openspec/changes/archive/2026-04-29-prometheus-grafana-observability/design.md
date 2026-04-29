## Context

Backend 目前的 `observability.py` 使用自製 in-memory metrics store，透過 `GET /metrics` 回傳 JSON snapshot。資料存於 process 記憶體，重啟歸零。`docs/01_BACKEND_SPEC.md` 第 12 節要求暴露 Prometheus 格式指標，但目前尚未實作。

現有的 JSON `/metrics` endpoint 被 admin UI 和測試使用，必須保持不變。

## Goals / Non-Goals

**Goals:**
- backend 新增 `GET /metrics/prometheus` 輸出標準 Prometheus text format
- docker-compose 加入 prometheus + grafana service，metrics 持久化
- infra 設定檔 provision（datasource 自動掛載，不需要人工操作）
- admin 前端新增監控頁，iframe embed Grafana

**Non-Goals:**
- 替換現有 JSON `/metrics` endpoint
- 改動 brain/api 的 observability（brain 的 `/metrics` 已有 JSON，後續再處理）
- 設定 Grafana alert（VH-136 決策 3 待定）
- 高可用 / 叢集 Prometheus 部署

## Decisions

**Decision 1：用 `prometheus_client` 而非自己輸出 text format**
- `prometheus_client` 是 Python 官方 Prometheus client，output format 保證正確
- 但它有自己的 global registry，與現有 `_counters`/`_timings` 不直接相容
- 做法：在 backend 側建立 `prometheus_client` 的 Counter/Histogram/Gauge，與現有 `increment_counter`/`record_timing` 並行呼叫（bridge pattern）
- 原有 JSON `/metrics` 完全不動，兩套並存
- 替代方案：自己實作 text format 輸出 → 格式容易出錯，維護成本高，放棄

**Decision 2：Grafana 用 iframe embed，不自己刻圖表**
- Grafana 本身就是完整 dashboard UI，embed 零開發成本
- admin 前端只需要一個帶 iframe 的頁面，指向 `http://localhost/grafana`
- Grafana 透過 nginx 反向代理，走同一個 host port（8787 → /grafana）
- 替代方案：串 Prometheus HTTP API 自己畫圖 → 開發成本高，放棄

**Decision 3：Grafana datasource 用 provisioning 自動掛載**
- 啟動時自動掛 Prometheus datasource，不需要人工在 UI 點設定
- 透過 `infra/grafana/provisioning/datasources/prometheus.yaml` 完成

## Risks / Trade-offs

- **兩套 metrics 並存** → 短期維護兩份，長期可考慮移除 JSON endpoint，但目前不做
- **prometheus_client global registry** → 測試時需要注意 registry 狀態污染，用 `REGISTRY.unregister` 清理
- **iframe 跨域** → Grafana 設定 `GF_SERVER_ROOT_URL` 和 `GF_SERVER_SERVE_FROM_SUB_PATH` 確保 nginx sub-path 正常，需測試

## Migration Plan

1. backend 加 `prometheus_client` 依賴，加 bridge + endpoint
2. 加 infra 設定檔
3. docker-compose 加兩個 service + volume
4. nginx 加 `/grafana` proxy 規則（走現有 admin nginx config）
5. admin 前端加監控頁路由
6. `docker compose up -d prometheus grafana` 驗證

Rollback：拿掉 prometheus/grafana service，刪 `/metrics/prometheus` endpoint，前端刪監控頁。

## Open Questions

- brain 的 `/brain/metrics` endpoint 格式是否也要輸出 Prometheus format？（本次 non-goal，但 prometheus.yml 已預留 scrape job）
- Grafana admin 密碼放 `.env` 還是 `backend/.env`？建議放專屬 `infra/.env`
