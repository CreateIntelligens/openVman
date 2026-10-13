"""ensure-runtime-secrets.sh 不能在資料庫已存在時悄悄換掉加密金鑰。"""

from __future__ import annotations

import shutil
import sqlite3
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


def _database(path: Path, *, secrets: int, table: str = "model_provider_secrets") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(f"CREATE TABLE {table} (credential_id TEXT, ciphertext TEXT)")
    connection.executemany(
        f"INSERT INTO {table} VALUES (?, 'x')", [(f"k{index}",) for index in range(secrets)],
    )
    connection.commit()
    connection.close()


def test_missing_secret_with_saved_keys_stops(tmp_path):
    deployment = _deployment(tmp_path, "SESSION_JWT_SECRET=keep\n")
    _database(deployment / "data" / "auth" / "accounts.db", secrets=2)

    result = _run(deployment)

    assert result.returncode == 1
    assert "already holds 2 encrypted API key(s)" in result.stderr
    assert _value(deployment, "DECISION_PROVIDER_ENCRYPTION_SECRET") == ""


def test_keys_saved_by_the_previous_release_also_stop(tmp_path):
    deployment = _deployment(tmp_path, "")
    _database(deployment / "data" / "auth" / "accounts.db", secrets=1, table="decision_provider_secrets")

    assert _run(deployment).returncode == 1


def test_database_without_saved_keys_still_gets_a_secret(tmp_path):
    """只靠 watchtower 部署、從沒跑過這支腳本的機器：DB 在但沒存過金鑰，照常產生。"""
    deployment = _deployment(tmp_path, "")
    _database(deployment / "data" / "auth" / "accounts.db", secrets=0)

    result = _run(deployment)

    assert result.returncode == 0, result.stderr
    assert len(_value(deployment, "DECISION_PROVIDER_ENCRYPTION_SECRET")) == 64


def test_unreadable_database_is_treated_as_holding_keys(tmp_path):
    deployment = _deployment(tmp_path, "")
    (deployment / "data" / "auth").mkdir(parents=True)
    (deployment / "data" / "auth" / "accounts.db").write_bytes(b"not a database")

    assert _run(deployment).returncode == 1


def test_custom_database_path_is_honoured(tmp_path):
    deployment = _deployment(tmp_path, "AUTH_DATABASE_PATH=/data/custom/auth.db\n")
    _database(deployment / "data" / "custom" / "auth.db", secrets=1)

    assert _run(deployment).returncode == 1


def test_existing_secret_is_left_alone_even_with_a_database(tmp_path):
    deployment = _deployment(tmp_path, "DECISION_PROVIDER_ENCRYPTION_SECRET=original\n")
    _database(deployment / "data" / "auth" / "accounts.db", secrets=1)

    assert _run(deployment).returncode == 0
    assert _value(deployment, "DECISION_PROVIDER_ENCRYPTION_SECRET") == "original"
