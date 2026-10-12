"""Successful ASR uploads meter media duration without breaking transcripts."""

import io
import subprocess
import wave
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    AuthTransport,
    CurrentAccount,
    get_current_account,
    require_admin,
)
from app.auth.models import AccountRole
from app.auth.runtime import get_auth_runtime
from app.gateway import ingestion_audio, worker
from app.routes import asr


def _wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 8000)
    return buffer.getvalue()


@pytest.fixture
def asr_client(monkeypatch):
    account = CurrentAccount(
        user=SimpleNamespace(id="owner-1", role=AccountRole.ADMIN),
        transport=AuthTransport.API_KEY,
        api_key=SimpleNamespace(key_id="key-a", user_id="owner-1"),
    )
    app = FastAPI()
    app.include_router(asr.router)
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[require_admin] = lambda: account

    async def routes(*_args):
        return ["zh"]

    async def prompt(*_args):
        return "詞表"

    async def transcribe(*_args, **_kwargs):
        return SimpleNamespace(content="辨識結果", provider="breeze")

    monkeypatch.setattr(asr.language_routes_mod, "effective_routes", routes)
    monkeypatch.setattr(asr.language_routes_mod, "resolve_project", lambda *a: "p1")
    monkeypatch.setattr(asr.asr_glossary_mod, "project_asr_prompt", prompt)
    monkeypatch.setattr(ingestion_audio, "transcribe", transcribe)
    monkeypatch.setattr(worker, "_account_asr_provider", lambda *_a: "r2t2")
    usage = []
    monkeypatch.setattr(asr, "record_usage_event", lambda **kw: usage.append(kw))
    return TestClient(app), usage


@pytest.mark.parametrize("route", ["transcribe", "preview"])
def test_upload_meters_decoded_duration_under_actual_provider(asr_client, route):
    client, usage = asr_client
    response = client.post(
        f"/api/v1/asr/{route}",
        files={"file": ("clip.wav", _wav(), "audio/wav")},
        data={"project_id": "p1"},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "辨識結果"
    assert len(usage) == 1
    assert usage[0]["provider"] == "breeze"
    assert usage[0]["kind"] == "asr"
    assert usage[0]["unit_type"] == "seconds"
    assert usage[0]["units"] == pytest.approx(0.5)
    assert usage[0]["scope"] == {
        "user_id": "owner-1", "role": "admin",
        "principal_type": "api_key", "principal_id": "key-a",
        "project_id": "p1", "channel": "http",
    }


@pytest.mark.parametrize("failure", ["probe", "ledger", "engine"])
def test_metering_failure_or_unknown_duration_preserves_transcript(
    asr_client, monkeypatch, failure,
):
    client, usage = asr_client
    if failure == "probe":
        monkeypatch.setattr(asr, "_audio_seconds", lambda *_: None)
    elif failure == "ledger":
        def fail(**_kwargs):
            raise RuntimeError("ledger down")

        monkeypatch.setattr(asr, "record_usage_event", fail)
    else:
        async def no_engine(*_args, **_kwargs):
            return SimpleNamespace(content="（音訊轉錄失敗）", provider="")

        monkeypatch.setattr(ingestion_audio, "transcribe", no_engine)
    response = client.post(
        "/api/v1/asr/transcribe",
        files={"file": ("clip.wav", _wav(), "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json()["text"]
    assert usage == []


def test_compressed_duration_uses_ffprobe_and_times_out_safely(tmp_path, monkeypatch):
    path = tmp_path / "clip.webm"
    path.write_bytes(b"not-wav")
    seen = []

    def probe(args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(stdout="2.75\n")

    monkeypatch.setattr(asr.subprocess, "run", probe)
    assert asr._audio_seconds(str(path)) == 2.75
    assert seen[0][0][-1] == str(path)
    assert seen[0][1]["timeout"] == 5

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(asr.subprocess, "run", timeout)
    assert asr._audio_seconds(str(path)) is None


def test_asr_openapi_exposes_transcript_fields(asr_client):
    client, _usage = asr_client
    schema = client.get("/openapi.json").json()
    fields = schema["components"]["schemas"]["AsrTranscription"]["properties"]
    assert set(fields) == {
        "text", "provider", "elapsed_seconds", "language",
        "language_check", "language_routes", "glossary",
    }
    for route in ("transcribe", "preview"):
        operation = schema["paths"][f"/api/v1/asr/{route}"]["post"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/AsrTranscription",
        }


def test_real_bearer_keys_reach_asr_metering_and_revocation_stops_usage(asr_client):
    client, usage = asr_client
    client.app.dependency_overrides.clear()
    runtime = get_auth_runtime()
    owner = runtime.users.create(
        username="service-owner", password_hash="unused", role=AccountRole.USER,
    )
    issued = [
        runtime.api_keys.create(
            actor_id=owner.id, user_id=owner.id, label=f"service-{index}",
        )
        for index in range(2)
    ]
    for record, credential in issued:
        response = client.post(
            "/api/v1/asr/transcribe",
            headers={"Authorization": f"Bearer {credential}"},
            files={"file": ("clip.wav", _wav(), "audio/wav")},
        )
        assert response.status_code == 200
        assert usage[-1]["scope"]["principal_id"] == record.key_id
        assert usage[-1]["scope"]["principal_type"] == "api_key"
        assert usage[-1]["scope"]["user_id"] == owner.id
    record, credential = issued[0]
    runtime.api_keys.revoke(
        actor_id=owner.id, key_id=record.key_id,
    )
    response = client.post(
        "/api/v1/asr/transcribe",
        headers={"Authorization": f"Bearer {credential}"},
        files={"file": ("clip.wav", _wav(), "audio/wav")},
    )
    assert response.status_code == 401
    assert len(usage) == 2
