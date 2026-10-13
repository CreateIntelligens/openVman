"""Documentation privacy regressions use fabricated identifiers only."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_document_privacy.py"
SPEC = importlib.util.spec_from_file_location("document_privacy", SCRIPT)
privacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(privacy)


@pytest.mark.parametrize(("value", "category"), [
    ("10.70.80.90", "private-ip"),
    ("172.20.30.40", "private-ip"),
    ("192.168.70.80", "private-ip"),
    ("169.254.20.30", "private-ip"),
    ("93.184.215.14", "real-ip"),
    ("02:11:22:33:44:55", "mac-address"),
    ("02-11-22-33-44-55", "mac-address"),
    ("usr_" + "a" * 32, "account-id"),
    ("proj-" + "a" * 10, "project-id"),
    ("dev-" + "b" * 10, "project-id"),
    ("esg-" + "c" * 10, "project-id"),
    ("ffffffff-ffff-4fff-8fff-ffffffffffff", "observation-id"),
    ("ovk_" + "a" * 32 + ".fabricated-secret", "account-key"),
    ("sk-proj-" + "a" * 32, "credential"),
    ("ghp_" + "a" * 36, "credential"),
    ("AKIA" + "A" * 16, "credential"),
    ("AIza" + "a" * 35, "credential"),
    ("eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20, "jwt"),
    ("Bearer " + "a" * 40, "bearer-secret"),
    ("-----BEGIN PRIVATE KEY-----", "private-key"),
    ("/home/private-operator/repo", "personal-home"),
    ("/Users/private-operator/repo", "personal-home"),
    ("operator@unreviewed-company.org", "personal-email"),
    ("https://unreviewed-company.org/api", "unreviewed-url-host"),
    ("https://user:password@api.example.com", "url-credential"),
    ('{"username": "private-operator"}', "literal-username"),
    ("python test.py --user private-operator", "literal-username"),
])
def test_sensitive_formats_are_rejected(value, category):
    assert category in privacy.line_categories(value)


@pytest.mark.parametrize("value", [
    "https://api.example.com/v1", "https://shop.example", "http://service.test",
    "https://attacker.invalid", "http://machine.localhost",
    "http://127.0.0.1:8000", "http://0.0.0.0:8000", "http://[::1]:8000",
    "http://192.0.2.10:8787", "http://198.51.100.10", "http://203.0.113.10",
    "http://localhost", "http://embedding:8200", "http://index-tts-vllm:8011",
    "https://YOUR_OPENVMAN_HOST/api", "https://<host>/api", "https://${HOST}/api",
    "https://github.com/CreateIntelligens/openVman/releases",
    "https://ghcr.io/CreateIntelligens/openvman", "https://huggingface.co/model",
    "https://api.typesafe.ai/v1/systemone", "https://nen.com.tw/v1",
    "https://ai.google.dev/gemini-api", "https://developers.openai.com/api",
    "https://www.evak-pumps.com/catalog.pdf", "sales@evak-pumps.com",
    "https://www.motc.gov.tw", "https://www.ntu.edu.tw", "https://www.cwa.gov.tw",
    "privacy@typesafe.ai", "operator@example.com", "person@internal.test",
    "/home/operator/openVman", "/home/example/repo", "/Users/example/repo",
    "project_id=example-hospital-project", "Authorization: Bearer ${API_KEY}",
    "00000000-0000-0000-0000-000000000000",
    "123e4567-e89b-12d3-a456-426614174000",
    "550e8400-e29b-41d4-a716-446655440000",
    "sha256=" + "a" * 64,
    '{"username": "<username>"}',
    "python test.py --user example-user",
    "python test.py --username ${BOOTSTRAP_USERNAME}",
])
def test_reserved_public_and_service_examples_are_allowed(value):
    assert not privacy.line_categories(value)


@pytest.mark.parametrize(("path", "expected"), [
    ("README.md", True), ("docs/operator.rst", True), ("notes.adoc", True),
    ("docs/operations.txt", True), ("requirements-dev.txt", False),
    ("docs/requirements.md", True),
    ("backend/requirements.txt", False), ("CMakeLists.txt", False),
    ("LICENSE.txt", False), ("vendor/private/README.md", False),
    ("node_modules/package/README.md", False), ("data/export.md", False),
    ("runtime/session.md", False), (".remember/recent.md", False),
    (".worktree/branch/README.md", False), ("backend/app/main.py", False),
    ("examples/embed.html", True), ("frontend/index.html", False),
    ("scripts/experiments/cases/results.json", True),
    ("scripts/experiments/cases/questions.jsonl", True),
    ("scripts/experiments/cases/answers.csv", True),
    ("scripts/experiments/catalog/_catalog.yaml", True),
    ("scripts/experiments/catalog/config.yml", True),
    ("docker-compose.yml", False),
    ("scripts/voice_e2e/cases/test.json", True), ("backend/config.json", False),
])
def test_document_selection(path, expected):
    assert privacy.is_document(path) is expected


def test_cli_scans_tracked_and_untracked_without_echoing_secrets(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    tracked = tmp_path / "tracked.md"
    tracked.write_text("Safe public documentation.\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.md"], check=True)
    secret = "ovk_" + "b" * 32 + ".fabricated-private-payload"
    tracked.write_text(secret + "\n")
    (tmp_path / "new.md").write_text("/home/private-operator/repo\n")
    (tmp_path / ".gitignore").write_text("ignored.md\n")
    (tmp_path / "ignored.md").write_text(secret)
    (tmp_path / "LICENSE.txt").write_text(secret)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "new.md:1: personal-home", "tracked.md:1: account-key",
    ]
    assert secret not in result.stdout + result.stderr
    assert "private-operator" not in result.stdout + result.stderr


def test_scan_error_does_not_echo_git_errors_or_environment(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ".:1: scan-error\n"
    assert result.stderr == ""


def test_repository_documentation_has_no_identifying_patterns():
    findings = privacy.scan(ROOT)
    assert not findings, "\n".join(
        f"{path}:{number}: {category}" for path, number, category in findings
    )
