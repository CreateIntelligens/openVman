"""ensure-runtime-secrets.sh 不能在資料庫已存在時悄悄換掉加密金鑰。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _deployment(tmp_path: Path, env: str) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "ensure-runtime-secrets.sh", tmp_path / "scripts")
    (tmp_path / ".env.example").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(env, encoding="utf-8")
    return tmp_path


def _run(deployment: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(deployment / "scripts" / "ensure-runtime-secrets.sh")],
        capture_output=True, text=True, check=False,
    )


def _value(deployment: Path, key: str) -> str:
    for line in (deployment / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


def test_fresh_deployment_generates_every_secret(tmp_path):
    deployment = _deployment(tmp_path, "")

    result = _run(deployment)

    assert result.returncode == 0, result.stderr
    assert len(_value(deployment, "DECISION_PROVIDER_ENCRYPTION_SECRET")) == 64


def test_missing_encryption_secret_with_existing_database_stops(tmp_path):
    deployment = _deployment(tmp_path, "SESSION_JWT_SECRET=keep\n")
    (deployment / "data" / "auth").mkdir(parents=True)
    (deployment / "data" / "auth" / "accounts.db").write_bytes(b"")

    result = _run(deployment)

    assert result.returncode == 1
    assert "accounts.db already exists" in result.stderr
    assert _value(deployment, "DECISION_PROVIDER_ENCRYPTION_SECRET") == ""


def test_custom_database_path_is_honoured(tmp_path):
    deployment = _deployment(tmp_path, "AUTH_DATABASE_PATH=/data/custom/auth.db\n")
    (deployment / "data" / "custom").mkdir(parents=True)
    (deployment / "data" / "custom" / "auth.db").write_bytes(b"")

    assert _run(deployment).returncode == 1


def test_existing_secret_is_left_alone_even_with_a_database(tmp_path):
    deployment = _deployment(tmp_path, "DECISION_PROVIDER_ENCRYPTION_SECRET=original\n")
    (deployment / "data" / "auth").mkdir(parents=True)
    (deployment / "data" / "auth" / "accounts.db").write_bytes(b"")

    assert _run(deployment).returncode == 0
    assert _value(deployment, "DECISION_PROVIDER_ENCRYPTION_SECRET") == "original"
