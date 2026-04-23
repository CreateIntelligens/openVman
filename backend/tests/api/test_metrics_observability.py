"""Regression tests for backend metrics and Prometheus exposure."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.responses import Response
from fastapi.testclient import TestClient


def test_normalize_http_metrics_endpoint_prefers_route_template():
    from types import SimpleNamespace

    from app.observability import normalize_http_metrics_endpoint

    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/skills/demo/files"),
        scope={"route": SimpleNamespace(path="/api/skills/{skill_id}/files")},
    )

    assert normalize_http_metrics_endpoint(request) == "/api/skills/{skill_id}/files"


def test_should_record_http_metrics_skips_health_and_metrics_routes():
    from app.observability import should_record_http_metrics

    assert should_record_http_metrics("/healthz") is False
    assert should_record_http_metrics("/metrics") is False
    assert should_record_http_metrics("/metrics/prometheus") is False
    assert should_record_http_metrics("/api/health") is False
    assert should_record_http_metrics("/api/metrics") is False
    assert should_record_http_metrics("/v1/audio/speech") is True


def test_record_timing_uses_bounded_history():
    import app.observability as obs

    obs.reset_metrics()
    for i in range(obs._TIMING_HISTORY_LIMIT + 25):
        obs.record_timing("bounded_metric", float(i))

    assert len(obs._timings["bounded_metric"]["history"]) == obs._TIMING_HISTORY_LIMIT

    snapshot = obs.get_metrics_snapshot()
    bucket = snapshot["timings"]["bounded_metric"]
    assert bucket["count"] == obs._TIMING_HISTORY_LIMIT + 25
    assert bucket["max_ms"] == obs._TIMING_HISTORY_LIMIT + 24


def test_http_5xx_does_not_increment_global_error_metric():
    import app.observability as obs

    obs.reset_metrics()
    before = obs.get_prometheus_sample_value("vman_error_total")

    obs.record_http_request(
        endpoint="/v1/audio/speech",
        method="POST",
        status_code=503,
        duration_ms=12.5,
    )

    after = obs.get_prometheus_sample_value("vman_error_total")
    snapshot = obs.get_metrics_snapshot()

    assert after == before
    assert snapshot["counters"]["http_errors_5xx_total|endpoint=/v1/audio/speech|method=POST|status_code=503"] == 1


def test_metrics_prometheus_route_delegates_to_observability():
    from app.main import app

    with patch("app.routes.admin.build_prometheus_response", return_value=Response(content=b"ok", media_type="text/plain")) as build:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/metrics/prometheus")

    assert response.status_code == 200
    assert response.content == b"ok"
    build.assert_called_once_with()


def test_http_metrics_middleware_uses_route_template_for_proxy_paths(monkeypatch):
    import app.main as main

    captured: list[dict[str, object]] = []

    class _FailingClient:
        async def send(self, *args, **kwargs):
            import httpx

            raise httpx.ConnectError("refused")

        def build_request(self, *args, **kwargs):
            return object()

    monkeypatch.setattr(
        main,
        "record_http_request",
        lambda **kwargs: captured.append(kwargs),
    )
    monkeypatch.setattr(
        main._brain_proxy_http,
        "get",
        lambda: _FailingClient(),
    )

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/api/skills/demo/files")

    assert response.status_code == 502
    assert captured[0]["endpoint"] == "/api/skills/{skill_id}/files"


def test_http_metrics_middleware_skips_metrics_routes(monkeypatch):
    import app.main as main

    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        main,
        "record_http_request",
        lambda **kwargs: captured.append(kwargs),
    )

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert captured == []
