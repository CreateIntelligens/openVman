"""Account keys select ASR per request without sharing mutable preferences."""

import asyncio
import io
import json
import wave
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthTransport, CurrentAccount
from app.auth.models import AccountRole, ResourceType
from app.auth.runtime import get_auth_runtime
from app.gateway import asr_stream, ingestion_audio
from app.routes import asr

_BASE_GRANTS = [
    (ResourceType.PROJECT, "p1"),
    (ResourceType.AVATAR_CHARACTER, "a1"),
    (ResourceType.CUSTOM_VOICE, "v1"),
]
_DEFAULTS = ("p1", "a1", "indextts", "v1")


def _wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "breeze")
    monkeypatch.setenv("ASR_BREEZE_URL", "http://breeze.test")
    monkeypatch.setenv("WHISPER_API_KEY", "test-only")
    monkeypatch.setenv("ASR_SENSEVOICE_URL", "http://sensevoice.test")
    monkeypatch.setenv("ASR_R2T2_URL", "")
    monkeypatch.setenv("ASR_R2T2_DEV_URL", "")
    runtime = get_auth_runtime()
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    for resource_type, resource_id in _BASE_GRANTS:
        runtime.resources.upsert_system_resource(
            resource_type=resource_type, resource_id=resource_id,
            metadata={"provider": "indextts"},
        )
    for engine in ("breeze", "openai", "gemini-live", "r2t2"):
        runtime.resources.upsert_system_resource(
            resource_type=ResourceType.ASR_ENGINE, resource_id=engine,
        )
    owner = runtime.users.create(
        username="asr-client", password_hash="unused", role=AccountRole.USER,
        created_by=root.id,
        grants=_BASE_GRANTS + [
            (ResourceType.ASR_ENGINE, engine)
            for engine in ("breeze", "openai", "gemini-live", "r2t2")
        ],
        defaults=_DEFAULTS,
    )
    runtime.account_access.set_asr_provider(owner.id, "breeze")
    keys = [
        runtime.api_keys.create(actor_id=owner.id, user_id=owner.id, label=name)
        for name in ("kiosk-a", "kiosk-b")
    ]
    app = FastAPI()
    app.include_router(asr.router)
    app.include_router(asr_stream.router)

    async def routes(*args):
        return ["zh"]

    async def prompt(*args):
        return "詞表"

    async def no_usage(*args, **kwargs):
        pass

    monkeypatch.setattr(asr.language_routes_mod, "effective_routes", routes)
    monkeypatch.setattr(asr.asr_glossary_mod, "project_asr_prompt", prompt)
    monkeypatch.setattr(asr, "_record_transcription_usage", no_usage)
    monkeypatch.setattr(ingestion_audio, "_unreachable_until", {})
    attempts = []

    def adapter(engine):
        async def run(*args, **kwargs):
            attempts.append(engine)
            return f"{engine} 辨識結果"

        return run

    monkeypatch.setattr(ingestion_audio, "_TRANSCRIBERS", {
        engine: adapter(engine)
        for engine in ("breeze", "openai", "sensevoice", "r2t2")
    })
    return app, runtime, root, owner, keys, attempts


def _upload(client, key, provider=None):
    data = {} if provider is None else {"provider": provider}
    return client.post(
        "/api/v1/asr/transcribe",
        headers={"Authorization": f"Bearer {key}"},
        files={"file": ("clip.wav", _wav(), "audio/wav")}, data=data,
    )


def test_concurrent_keys_keep_their_engine_and_account_preference(setup, monkeypatch):
    app, runtime, _root, owner, keys, attempts = setup

    async def exercise():
        both_started = asyncio.Event()

        def adapter(engine):
            async def run(*args, **kwargs):
                attempts.append(engine)
                if len(attempts) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), 3)
                return engine

            return run

        for engine in ("breeze", "openai"):
            monkeypatch.setitem(ingestion_audio._TRANSCRIBERS, engine, adapter(engine))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            replies = await asyncio.gather(*[
                client.post(
                    "/api/v1/asr/transcribe",
                    headers={"Authorization": f"Bearer {keys[index][1]}"},
                    files={"file": ("clip.wav", _wav(), "audio/wav")},
                    data={"provider": engine},
                )
                for index, engine in enumerate(("breeze", "openai"))
            ])
        assert [response.status_code for response in replies] == [200, 200]
        assert [response.json()["provider"] for response in replies] == [
            "breeze", "openai",
        ]
        assert [response.json()["text"] for response in replies] == [
            "breeze", "openai",
        ]

    asyncio.run(exercise())
    assert runtime.account_access.get_asr_provider(owner.id) == "breeze"


@pytest.mark.parametrize(("provider", "code"), [
    ("sensevoice", 403), ("browser", 422), ("gemini-live", 422),
    ("unknown", 422), ("r2t2", 503),
])
def test_rejects_ungranted_wrong_mode_or_unconfigured_before_inference(
    setup, provider, code,
):
    app, _runtime, _root, _owner, keys, attempts = setup
    with TestClient(app) as client:
        response = _upload(client, keys[0][1], provider)
    assert response.status_code == code
    assert attempts == []


def test_revoking_grant_blocks_existing_key_on_next_request(setup):
    app, runtime, root, owner, keys, attempts = setup
    with TestClient(app) as client:
        assert _upload(client, keys[0][1], "openai").status_code == 200
        runtime.account_access.replace(
            user_id=owner.id, granted_by=root.id,
            grants=_BASE_GRANTS + [(ResourceType.ASR_ENGINE, "breeze")],
            defaults=_DEFAULTS,
        )
        assert _upload(client, keys[0][1], "openai").status_code == 403
    assert attempts == ["openai"]


def test_explicit_failure_is_502_and_never_falls_back(setup, monkeypatch):
    app, _runtime, _root, _owner, keys, attempts = setup

    async def fail(*args, **kwargs):
        attempts.append("openai")
        raise RuntimeError("upstream down")

    monkeypatch.setitem(ingestion_audio._TRANSCRIBERS, "openai", fail)
    with TestClient(app) as client:
        response = _upload(client, keys[0][1], "openai")
    assert response.status_code == 502
    assert attempts == ["openai"]


@pytest.mark.parametrize("provider", [None, "", "  "])
def test_omitted_provider_keeps_preference_and_granted_fallbacks(
    setup, monkeypatch, provider,
):
    app, runtime, _root, owner, keys, attempts = setup

    async def fail(*args, **kwargs):
        attempts.append("breeze")
        raise RuntimeError("upstream down")

    monkeypatch.setitem(ingestion_audio._TRANSCRIBERS, "breeze", fail)
    with TestClient(app) as client:
        response = _upload(client, keys[0][1], provider)
    assert response.status_code == 200
    assert response.json()["provider"] == "openai"
    assert attempts == ["breeze", "openai"]
    assert runtime.account_access.get_asr_provider(owner.id) == "breeze"


def test_legacy_fallback_does_not_try_ungranted_engine(setup, monkeypatch):
    app, _runtime, _root, _owner, keys, attempts = setup

    async def fail(*args, **kwargs):
        attempts.append("failed")
        raise RuntimeError("upstream down")

    for engine in ("breeze", "openai"):
        monkeypatch.setitem(ingestion_audio._TRANSCRIBERS, engine, fail)
    with TestClient(app) as client:
        response = _upload(client, keys[0][1])
    assert response.status_code == 200
    assert response.json()["provider"] == ""
    assert "sensevoice" not in attempts


def test_explicit_provider_is_not_overridden_by_taiwanese_route(setup, monkeypatch):
    app, _runtime, _root, _owner, keys, attempts = setup

    async def routes(*args):
        return ["zh", "nan"]

    async def heard(*args, **kwargs):
        return SimpleNamespace(language="nan", result="nan", ms=1)

    monkeypatch.setattr(asr.language_routes_mod, "effective_routes", routes)
    monkeypatch.setattr(asr.language_routes_mod, "detect_taiwanese", heard)
    with TestClient(app) as client:
        response = _upload(client, keys[0][1], "openai")
    assert response.status_code == 200
    assert response.json()["provider"] == "openai"
    assert response.json()["language"] == "nan"
    assert attempts == ["openai"]


def test_project_authorization_error_keeps_404(setup, monkeypatch):
    app, _runtime, _root, _owner, keys, attempts = setup

    async def forbidden(*args):
        raise HTTPException(status_code=404, detail="Resource not found")

    monkeypatch.setattr(asr.language_routes_mod, "effective_routes", forbidden)
    with TestClient(app) as client:
        response = _upload(client, keys[0][1], "openai")
    assert response.status_code == 404
    assert attempts == []


def test_openapi_documents_optional_provider(setup):
    app, *_rest = setup
    schema = app.openapi()
    request = schema["paths"]["/api/v1/asr/transcribe"]["post"]["requestBody"]
    reference = request["content"]["multipart/form-data"]["schema"]["$ref"]
    body = schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]
    assert body["properties"]["provider"]["default"] == ""
    assert "provider" not in body["required"]
    assert {"403", "422", "502", "503"} <= set(
        schema["paths"]["/api/v1/asr/transcribe"]["post"]["responses"],
    )


def test_stream_engine_override_obeys_current_grants_without_writing(setup):
    _app, runtime, root, owner, _keys, _attempts = setup
    account = CurrentAccount(user=owner, transport=AuthTransport.API_KEY)
    assert asr_stream._engine_for(account, "gemini-live") == "gemini-live"
    assert asr_stream._engine_for(account, "r2t2-live") == ""
    assert asr_stream._engine_for(account, "openai") == ""
    runtime.account_access.replace(
        user_id=owner.id, granted_by=root.id,
        grants=_BASE_GRANTS + [(ResourceType.ASR_ENGINE, "breeze")],
        defaults=_DEFAULTS,
    )
    assert asr_stream._engine_for(account, "gemini-live") == ""
    assert runtime.account_access.get_asr_provider(owner.id) == "breeze"


def test_bearer_stream_override_works_without_changing_batch_preference(
    setup, monkeypatch,
):
    app, runtime, root, owner, keys, _attempts = setup
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    monkeypatch.setattr(
        asr_stream, "resolve_gemini_credential",
        lambda project_id, runtime=None: SimpleNamespace(
            api_key="test-only", source="shared",
            credential_id="gemini", configured=True,
        ),
    )
    connections = []

    class Upstream:
        async def __aenter__(self):
            connections.append(self)
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, message):
            assert isinstance(json.loads(message), dict)

        async def recv(self):
            return json.dumps({"setupComplete": {}})

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(asr_stream.websockets, "connect", lambda *a, **kw: Upstream())
    headers = {"Authorization": f"Bearer {keys[0][1]}"}
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/asr/stream?engine=gemini-live", headers=headers,
        ) as ws:
            assert ws.receive_json() == {"type": "ready"}
        runtime.account_access.replace(
            user_id=owner.id, granted_by=root.id,
            grants=_BASE_GRANTS + [(ResourceType.ASR_ENGINE, "breeze")],
            defaults=_DEFAULTS,
        )
        with client.websocket_connect(
            "/api/v1/asr/stream?engine=gemini-live", headers=headers,
        ) as ws:
            assert ws.receive_json() == {"type": "error", "code": "not_allowed"}
    assert len(connections) == 1
    assert runtime.account_access.get_asr_provider(owner.id) == "breeze"


def test_embed_cannot_override_and_admin_keeps_stream_preview(setup):
    _app, _runtime, _root, owner, _keys, _attempts = setup
    embed = CurrentAccount(
        user=owner, transport=AuthTransport.EMBED_KEY,
        embed_key=SimpleNamespace(),
    )
    admin = CurrentAccount(
        user=SimpleNamespace(role=AccountRole.ADMIN),
        transport=AuthTransport.BEARER,
    )
    assert asr_stream._engine_for(embed, "gemini-live") == ""
    assert asr_stream._engine_for(admin, "gemini-live") == "gemini-live"
