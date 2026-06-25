"""Regression tests for HTTPS support on the nginx edge proxy."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_admin_compose_exposes_https_port_and_cert_mount():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"${HTTPS_PORT:-8787}:443"' in compose
    assert "./infra/nginx/certs:/etc/nginx/certs" in compose


def test_admin_nginx_listens_on_https_with_project_cert_paths():
    config = (ROOT / "frontend" / "admin" / "nginx" / "default.conf").read_text(encoding="utf-8")

    assert "listen 443 ssl;" in config
    assert "ssl_certificate /etc/nginx/certs/openvman.crt;" in config
    assert "ssl_certificate_key /etc/nginx/certs/openvman.key;" in config


def test_admin_dev_image_prepares_self_signed_cert_before_nginx_starts():
    dockerfile = (ROOT / "frontend" / "admin" / "Dockerfile.dev").read_text(encoding="utf-8")
    supervisord = (ROOT / "frontend" / "admin" / "supervisord.conf").read_text(encoding="utf-8")
    cert_script = (ROOT / "frontend" / "admin" / "docker" / "ensure-https-cert.sh").read_text(encoding="utf-8")

    assert "openssl" in dockerfile
    assert "EXPOSE 80 443 5173" in dockerfile
    assert "ensure-https-cert" in supervisord
    assert "OPENVMAN_TLS_CERT_OWNER" in cert_script
    assert 'chown "$cert_owner"' in cert_script


def test_admin_dev_nginx_does_not_load_production_static_config():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "frontend" / "admin" / "Dockerfile.dev").read_text(encoding="utf-8")

    assert "./frontend/admin/nginx:/etc/nginx/http.d" not in compose
    assert "./frontend/admin/nginx/default.conf:/etc/nginx/http.d/default.conf:ro" in compose
    assert "COPY nginx/ /etc/nginx/http.d/" not in dockerfile
