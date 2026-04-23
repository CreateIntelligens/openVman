"""Regression tests for nginx monitoring proxy config."""

from __future__ import annotations

from pathlib import Path


def test_grafana_proxy_disables_buffering():
    config_path = Path(__file__).resolve().parents[3] / "frontend" / "admin" / "nginx" / "default.conf"
    config = config_path.read_text(encoding="utf-8")

    grafana_block = config.split("location /grafana/ {", 1)[1].split("}", 1)[0]

    assert "proxy_buffering off;" in grafana_block
