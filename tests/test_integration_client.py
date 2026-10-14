"""Verify the public integration flow against an isolated HTTP server."""

from __future__ import annotations

import importlib.util
import json
import ssl
import subprocess
import sys
import threading
from contextlib import contextmanager
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPSHandler

import pytest

_CLIENT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts/integration_client.py"
)
_SPEC = importlib.util.spec_from_file_location("integration_client", _CLIENT_PATH)
client = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(client)


CAPABILITIES = {
    "schema_version": 1,
    "defaults": {"project_id": "proj-opaque"},
    "projects": [{"project_id": "proj-opaque", "label": "顯示名稱"}],
    "asr": {"batch": [{"id": "r2t2", "configured": True}]},
}


@contextmanager
def server(*, mime="audio/wav", asr=None, status=200, redirect=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append((self.command, self.path, dict(self.headers), body))
            if redirect:
                self.send_response(302)
                self.send_header("Location", "/credential-leak")
                self.end_headers()
                return
            if status != 200:
                payload = b"ovk_test.never-print-this"
                content_type = "text/plain"
            elif self.path.endswith("/capabilities"):
                payload = json.dumps(CAPABILITIES).encode()
                content_type = "application/json"
            elif self.path.endswith("/transcribe"):
                payload = json.dumps(asr or {
                    "text": "產品支援嗎？", "provider": "r2t2", "language": "zh",
                }).encode()
                content_type = "application/json"
            elif self.path.endswith("/chat"):
                payload = json.dumps({"reply": "支援。"}).encode()
                content_type = "application/json"
            elif self.path.endswith("/tts/stream"):
                payload, content_type = b"test-audio", mime
            else:
                payload, content_type = b"unexpected request", "text/plain"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}/openvman", requests
    finally:
        http.shutdown()
        http.server_close()
        worker.join()


def cli_args(base, tmp_path):
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"sample-input")
    return [
        "--base-url", base, "--audio", str(audio),
        "--project-id", "proj-opaque", "--output", str(tmp_path / "reply.bad"),
    ]


@pytest.fixture(autouse=True)
def credential(monkeypatch):
    monkeypatch.setenv("OPENVMAN_API_KEY", "ovk_test.never-print-this")


@pytest.mark.parametrize("mime,suffix", [
    ("audio/wav; rate=48000", ".wav"),
    ("audio/mpeg", ".mp3"),
    ("audio/l16;rate=24000;channels=1", ".pcm"),
])
def test_full_flow_keeps_project_and_selections_per_request(
    tmp_path, capsys, mime, suffix
):
    with server(mime=mime) as (base, requests):
        args = cli_args(base, tmp_path) + [
            "--asr-provider", "r2t2", "--tts-provider", "cosyvoice",
            "--voice", "young-male-02",
        ]
        assert client.main(args) == 0
    assert [(method, path) for method, path, _, _ in requests] == [
        ("GET", "/openvman/api/v1/me/capabilities"),
        ("POST", "/openvman/api/v1/asr/transcribe"),
        ("POST", "/openvman/api/v1/chat"),
        ("POST", "/openvman/api/v1/tts/stream"),
    ]
    assert all(headers["Authorization"] == "Bearer ovk_test.never-print-this"
               for _, _, headers, _ in requests)
    _, _, headers, body = requests[1]
    message = BytesParser().parsebytes(
        f"Content-Type: {headers['Content-Type']}\r\n\r\n".encode() + body
    )
    parts = {part.get_param("name", header="Content-Disposition"):
             part.get_payload(decode=True) for part in message.get_payload()}
    assert parts == {
        "project_id": b"proj-opaque", "provider": b"r2t2",
        "file": b"sample-input",
    }
    chat = json.loads(requests[2][3])
    assert chat["message"] == "產品支援嗎？"
    assert chat["project_id"] == "proj-opaque"
    assert chat["session_id"].startswith("integration-")
    assert json.loads(requests[3][3]) == {
        "text": "支援。", "project_id": "proj-opaque", "speech_language": "zh",
        "provider": "cosyvoice", "voice": "young-male-02",
    }
    assert (tmp_path / f"reply{suffix}").read_bytes() == b"test-audio"
    assert "never-print-this" not in capsys.readouterr().out


def test_discover_does_not_create_chat_or_call_inference(capsys):
    with server() as (base, requests):
        assert client.main(["--base-url", base, "--discover-only"]) == 0
    assert len(requests) == 1
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1


def test_tts_format_is_sent_only_when_requested(tmp_path):
    with server(mime="audio/l16;rate=16000;channels=1") as (base, requests):
        assert client.main(cli_args(base, tmp_path) + ["--tts-format", "pcm16k"]) == 0
    assert json.loads(requests[3][3])["format"] == "pcm16k"
    assert (tmp_path / "reply.pcm").read_bytes() == b"test-audio"


def test_omitted_providers_remain_omitted(tmp_path):
    with server() as (base, requests):
        assert client.main(cli_args(base, tmp_path)) == 0
    assert b'name="provider"' not in requests[1][3]
    payload = json.loads(requests[3][3])
    assert "provider" not in payload
    assert "voice" not in payload
    assert "format" not in payload


def test_asr_legacy_failure_stops_before_chat(tmp_path, capsys):
    with server(asr={"provider": "", "text": "（音訊轉錄失敗）"}) as (base, requests):
        assert client.main(cli_args(base, tmp_path)) == 1
    assert len(requests) == 2
    assert "ASR 未產生有效結果" in capsys.readouterr().err


def test_unlisted_batch_provider_is_not_sent(tmp_path, capsys):
    with server() as (base, requests):
        args = cli_args(base, tmp_path) + ["--asr-provider", "gemini-live"]
        assert client.main(args) == 1
    assert len(requests) == 1
    assert "batch" in capsys.readouterr().err


def test_project_label_is_not_an_id(tmp_path, capsys):
    with server() as (base, requests):
        args = cli_args(base, tmp_path)
        args[args.index("--project-id") + 1] = "顯示名稱"
        assert client.main(args) == 1
    assert len(requests) == 1
    assert "project_id" in capsys.readouterr().err


def test_remote_text_cannot_echo_api_key(tmp_path, capsys):
    with server(asr={
        "provider": "r2t2", "text": "echo ovk_test.never-print-this",
    }) as (base, _):
        assert client.main(cli_args(base, tmp_path)) == 0
    captured = capsys.readouterr()
    assert "never-print-this" not in captured.out + captured.err
    assert "[REDACTED]" in captured.out


@pytest.mark.parametrize("options,expected", [
    ({"status": 403}, "HTTP 403"), ({"redirect": True}, "HTTP 302"),
])
def test_http_errors_and_redirects_do_not_expose_credentials(
    capsys, options, expected
):
    with server(**options) as (base, requests):
        assert client.main(["--base-url", base, "--discover-only"]) == 1
    assert len(requests) == 1
    captured = capsys.readouterr()
    assert expected in captured.err
    assert "never-print-this" not in captured.out + captured.err


def test_tls_context_verifies_certificates_and_hostnames():
    instance = client.Client("https://example.test/openvman", "test")
    https = next(handler for handler in instance.opener.handlers
                 if isinstance(handler, HTTPSHandler))
    assert https._context.verify_mode == ssl.CERT_REQUIRED
    assert https._context.check_hostname is True


def test_audio_does_not_overwrite_existing_file(tmp_path):
    destination = tmp_path / "reply.wav"
    destination.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        client.save_audio(b"new", "audio/wav", destination)
    assert destination.read_bytes() == b"keep"


@pytest.mark.parametrize("raw,mime", [
    (b"", "audio/wav"), (b"error", "application/json"),
])
def test_invalid_audio_is_not_saved(tmp_path, raw, mime):
    with pytest.raises(client.IntegrationError):
        client.save_audio(raw, mime, tmp_path / "reply")
    assert not list(tmp_path.iterdir())


def test_help_runs_without_dependencies_or_credentials(monkeypatch):
    monkeypatch.delenv("OPENVMAN_API_KEY", raising=False)
    script = Path(__file__).resolve().parents[1] / "scripts/integration_client.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--discover-only" in result.stdout
