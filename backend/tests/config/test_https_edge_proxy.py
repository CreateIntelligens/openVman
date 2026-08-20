"""Regression tests for HTTPS support on the nginx edge proxy."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.requires_repo_root

ROOT = Path(__file__).resolve().parents[3]


def test_admin_compose_exposes_https_port_and_cert_mount():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"${HTTPS_PORT:-8787}:443"' in compose
    assert "./infra/nginx/certs:/etc/nginx/certs" in compose


def test_admin_nginx_listens_on_https_with_project_cert_paths():
    config = (ROOT / "frontend" / "admin" / "nginx" / "http.d" / "default.conf").read_text(encoding="utf-8")

    assert "listen 443 ssl;" in config
    assert "ssl_certificate /etc/nginx/certs/openvman.crt;" in config
    assert "ssl_certificate_key /etc/nginx/certs/openvman.key;" in config


def test_admin_dev_image_prepares_self_signed_cert_before_nginx_starts():
    dockerfile = (ROOT / "frontend" / "admin" / "Dockerfile").read_text(encoding="utf-8")
    supervisord = (ROOT / "frontend" / "admin" / "supervisord.conf").read_text(encoding="utf-8")
    cert_script = (ROOT / "frontend" / "admin" / "docker" / "ensure-https-cert.sh").read_text(encoding="utf-8")

    assert "openssl" in dockerfile
    assert "EXPOSE 80 443 5173" in dockerfile
    assert "ensure-https-cert" in supervisord
    assert "OPENVMAN_TLS_CERT_OWNER" in cert_script
    assert 'chown "$cert_owner"' in cert_script


def test_admin_dev_nginx_does_not_load_production_static_config():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "frontend" / "admin" / "Dockerfile").read_text(encoding="utf-8")

    assert "./frontend/admin/nginx:/etc/nginx/http.d" not in compose
    assert "./frontend/admin/nginx/http.d:/etc/nginx/http.d:ro" in compose
    assert "COPY nginx/ /etc/nginx/http.d/" not in dockerfile


def test_native_public_proxy_supports_openvman_root_relative_routes():
    config = (ROOT / "infra" / "nginx" / "native" / "146-openvman.conf").read_text(encoding="utf-8")

    assert "location /openvman/" in config
    assert "location ^~ /admin/" in config
    assert "location = /admin/login" in config
    for route in ("admin", "api", "ws", "v1", "tts", "js", "wasm", "grafana", "vendor"):
        assert route in config
    assert "location = /widget.html" in config
    assert "proxy_pass https://127.0.0.1:8787" in config


def test_vite_hmr_follows_the_browser_https_origin():
    app_vite = (ROOT / "frontend" / "app" / "vite.config.ts").read_text(encoding="utf-8")
    admin_vite = (ROOT / "frontend" / "admin" / "vite.config.ts").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    # 不固定 clientPort，讓同一份設定同時支援主機 nginx 443
    # 與區網直連 Docker edge 8787。
    for config in (app_vite, admin_vite):
        assert 'protocol: "wss"' in config
        assert "clientPort:" not in config
        assert "process.env.PUBLIC_HTTPS_PORT" not in config
    assert 'path: "/@vite/hmr"' in app_vite
    assert "PUBLIC_HTTPS_PORT" not in compose
    assert "PUBLIC_HTTPS_PORT" not in env_example


def test_native_vhost_matches_its_template():
    """The deployed vhost must stay renderable from the template.

    146-openvman.conf is what currently runs; the template is what a new
    machine renders. If they drift, a fresh deploy silently loses whatever
    was hand-edited into the live file.
    """
    template = (
        ROOT / "infra" / "nginx" / "native" / "openvman.conf.template"
    ).read_text(encoding="utf-8")
    current = (
        ROOT / "infra" / "nginx" / "native" / "146-openvman.conf"
    ).read_text(encoding="utf-8")

    rendered = template
    for placeholder, value in (
        ("${PUBLIC_DOMAIN}", "146.5gao.ai"),
        (
            "${LETSENCRYPT_DIR}",
            "/home/human/openVman/infra/nginx/certs/letsencrypt",
        ),
        ("${EDGE_UPSTREAM}", "127.0.0.1:8787"),
        ("${ACME_WEBROOT}", "/usr/share/nginx/html"),
    ):
        rendered = rendered.replace(placeholder, value)

    # 範本開頭多一段說明用的註解，比對時逐行去掉。
    lines = rendered.splitlines()
    while lines and (lines[0].startswith("#") or not lines[0].strip()):
        lines.pop(0)
    body = "\n".join(lines)

    assert "${" not in body, "template still has unsubstituted placeholders"
    assert body.strip() == current.strip()


def test_public_https_setup_wraps_initial_certificate_nginx_and_cron(tmp_path):
    script = ROOT / "scripts" / "setup-public-https.sh"
    renew_script = ROOT / "scripts" / "renew-letsencrypt.sh"
    source = script.read_text(encoding="utf-8")
    assert os.access(script, os.X_OK)
    assert os.access(renew_script, os.X_OK)
    env = os.environ.copy()
    env.pop("PUBLIC_DOMAIN", None)
    env.pop("LETSENCRYPT_EMAIL", None)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PUBLIC_DOMAIN=avatar.example.com\n"
        "LETSENCRYPT_EMAIL=ops@example.com\n",
        encoding="utf-8",
    )
    env["OPENVMAN_ENV_FILE"] = str(env_file)

    result = subprocess.run(
        [str(script), "--dry-run"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "render nginx vhost" in result.stdout
    assert "issue initial Let's Encrypt certificate" in result.stdout
    assert "install and reload host nginx" in result.stdout
    assert "install idempotent renewal cron" in result.stdout
    assert "render-native-nginx.sh" in source
    assert "certbot" in source and "certonly" in source
    assert "nginx" in source and "systemctl" in source
    assert "crontab" in source and "renew-letsencrypt.sh" in source
    assert "cron_begin=" in source and "cron_end=" in source
    assert 'run_root test -s "$FULLCHAIN"' in source
    assert "prepare_nginx_rollback" in source and "nginx_backup" in source
    assert source.index("prepare_nginx_rollback\nrun_root install") < source.index(
        'run_root install -m 0644 "$RENDERED_CONFIG"',
    )
    assert "existing jobs were not changed" in source
