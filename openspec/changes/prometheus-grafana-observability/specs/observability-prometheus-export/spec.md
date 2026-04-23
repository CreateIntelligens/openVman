## ADDED Requirements

### Requirement: Backend exposes Prometheus text format metrics
Backend SHALL expose a `GET /metrics/prometheus` endpoint that returns metrics in Prometheus text exposition format, compatible with standard Prometheus scraping.

#### Scenario: Successful scrape
- **WHEN** Prometheus or any HTTP client sends `GET /metrics/prometheus`
- **THEN** the response has `Content-Type: text/plain; version=0.0.4` and HTTP 200
- **THEN** the body contains all defined metrics in Prometheus text format

#### Scenario: Required metrics present
- **WHEN** the endpoint is scraped after at least one request has been processed
- **THEN** the response includes `vman_ttfb_ms`, `vman_tts_latency_ms`, `vman_active_sessions`, `vman_error_total` as defined in BACKEND_SPEC section 12

#### Scenario: Existing JSON endpoint unaffected
- **WHEN** client sends `GET /metrics`
- **THEN** response remains JSON format, unchanged from current behaviour

### Requirement: Prometheus metrics bridge existing observability calls
The Prometheus metrics SHALL be updated in parallel with existing `increment_counter` and `record_timing` calls, without modifying call sites.

#### Scenario: Counter increment reflected in Prometheus
- **WHEN** `increment_counter("http_errors_5xx_total|...")` is called
- **THEN** the corresponding Prometheus counter increments by the same amount

#### Scenario: Timing reflected as histogram
- **WHEN** `record_timing("live_voice_latency_ms", value)` is called
- **THEN** `vman_ttfb_ms` Prometheus histogram observes the value
