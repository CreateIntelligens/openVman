"""Every voice path honours account grants ∩ project policy, and nothing more."""

from __future__ import annotations

import asyncio
import io
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import voice_policy
from app.auth.dependencies import AuthTransport, CurrentAccount
from app.auth.models import AccountRole, ResourceType
from app.auth.runtime import get_auth_runtime
from app.auth.voice_access import (
    embed_tts_providers,
    resolve_tts_voice,
    scoped_tts_providers,
    tts_fallback_voice,
)
from app.config import TTSRouterConfig
from app.gateway import asr_stream, dispatcher, ingestion_audio, worker
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.routes import asr, tts
from app.service import TTSRouterService
from app.tts_cache import make_cache_key

_ENGINES = ("breeze", "openai", "sensevoice", "gemini-live", "r2t2-live")
_GRANTED_ENGINES = ("breeze", "openai", "gemini-live", "r2t2-live")
_VOICES = {
    "index-a": {"provider": "indextts"},
    "cosy-a": {"provider": "cosyvoice", "runtime_key": "cosy-upstream"},
    "vox-a": {"provider": "voxcpm", "runtime_key": "vox-upstream"},
    "edge-a": {"provider": "edge-tts", "runtime_key": "zh-TW-YunJheNeural"},
}
_BASE_GRANTS = [
    (ResourceType.PROJECT, "p1"),
    (ResourceType.AVATAR_CHARACTER, "a1"),
    *((ResourceType.CUSTOM_VOICE, voice) for voice in _VOICES),
]
_DEFAULTS = ("p1", "a1", "indextts", "index-a")


def _wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "breeze")
    monkeypatch.setenv("ASR_BREEZE_URL", "http://breeze.test")
    monkeypatch.setenv("WHISPER_API_KEY", "test-only")
    monkeypatch.setenv("ASR_SENSEVOICE_URL", "http://sensevoice.test")
    monkeypatch.setenv("ASR_R2T2_URL", "")
    monkeypatch.setenv("ASR_R2T2_DEV_URL", "")
    runtime = get_auth_runtime()
    root = runtime.users.create_root(username="ai360", password_hash="unused")
    for resource_type, resource_id in [
        (ResourceType.PROJECT, "p1"),
        (ResourceType.AVATAR_CHARACTER, "a1"),
    ]:
        runtime.resources.upsert_system_resource(
            resource_type=resource_type, resource_id=resource_id,
        )
    for voice, metadata in _VOICES.items():
        runtime.resources.upsert_system_resource(
            resource_type=ResourceType.CUSTOM_VOICE, resource_id=voice,
            metadata=metadata,
        )
    for engine in _ENGINES:
        runtime.resources.upsert_system_resource(
            resource_type=ResourceType.ASR_ENGINE, resource_id=engine,
        )
    owner = runtime.users.create(
        username="member", password_hash="unused", role=AccountRole.USER,
        created_by=root.id,
        grants=_BASE_GRANTS + [
            (ResourceType.ASR_ENGINE, engine) for engine in _GRANTED_ENGINES
        ],
        defaults=_DEFAULTS,
    )
    runtime.account_access.set_asr_provider(owner.id, "breeze")
    _key_id, token = runtime.api_keys.create(
        actor_id=owner.id, user_id=owner.id, label="kiosk",
    )

    app = FastAPI()
    app.include_router(asr.router)
    app.include_router(asr_stream.router)

    async def routes(*args):
        return env.routes

    async def prompt(*args):
        return ""

    async def no_usage(*args, **kwargs):
        pass

    heard_projects: list[str] = []

    async def heard(*args, project_id=""):
        heard_projects.append(project_id)
        return SimpleNamespace(language="nan", result="nan", ms=1)

    monkeypatch.setattr(asr.language_routes_mod, "effective_routes", routes)
    monkeypatch.setattr(asr.language_routes_mod, "detect_taiwanese", heard)
    monkeypatch.setattr(asr.asr_glossary_mod, "project_asr_prompt", prompt)
    monkeypatch.setattr(asr, "_record_transcription_usage", no_usage)
    monkeypatch.setattr(ingestion_audio, "_unreachable_until", {})
    attempts: list[str] = []
    failing: set[str] = set()

    def adapter(engine):
        async def run(*args, **kwargs):
            attempts.append(engine)
            if engine in failing:
                raise RuntimeError("upstream down")
            return f"{engine} 辨識結果"

        return run

    monkeypatch.setattr(ingestion_audio, "_TRANSCRIBERS", {
        engine: adapter(engine) for engine in ("breeze", "openai", "sensevoice")
    })
    env = SimpleNamespace(
        runtime=runtime, root=root, owner=owner, token=token, app=app,
        attempts=attempts, failing=failing, routes=["zh"],
        heard_projects=heard_projects,
        account=CurrentAccount(user=owner, transport=AuthTransport.API_KEY),
    )
    return env


def _policy(env, **fields):
    return env.runtime.project_policies.replace(
        project_id="p1", updated_by=env.root.id, **fields,
    )


def _transcribe(env, provider=None, project_id="p1"):
    data = {"project_id": project_id}
    if provider is not None:
        data["provider"] = provider
    with TestClient(env.app) as client:
        return client.post(
            "/api/v1/asr/transcribe",
            headers={"Authorization": f"Bearer {env.token}"},
            files={"file": ("clip.wav", _wav(), "audio/wav")}, data=data,
        )


def _embed(project_id="p1", provider="", voice=""):
    return CurrentAccount(
        user=SimpleNamespace(id="embed:k1", role=AccountRole.USER),
        transport=AuthTransport.EMBED_KEY,
        embed_key=SimpleNamespace(
            key_id="k1", project_id=project_id,
            default_tts_provider=provider, default_tts_voice=voice,
        ),
    )


# --- Batch ASR -------------------------------------------------------------


def test_unset_policy_keeps_old_preference_and_fallback(env):
    env.failing.add("breeze")
    response = _transcribe(env)
    assert response.status_code == 200
    assert response.json()["provider"] == "openai"
    assert env.attempts == ["breeze", "openai"]


def test_explicit_provider_outside_project_is_403_before_inference(env):
    _policy(env, allowed_asr_engines=["breeze"])
    assert _transcribe(env, "openai").status_code == 403
    assert env.attempts == []
    assert _transcribe(env, "breeze").status_code == 200
    assert env.attempts == ["breeze"]


def test_explicit_provider_still_needs_the_account_grant(env):
    _policy(env, allowed_asr_engines=["breeze", "sensevoice"])
    assert _transcribe(env, "sensevoice").status_code == 403
    assert env.attempts == []


def test_blocked_preference_falls_to_project_default(env):
    _policy(env, allowed_asr_engines=["openai", "breeze"], default_asr_engine="openai")
    env.runtime.account_access.set_asr_provider(env.owner.id, "sensevoice")
    response = _transcribe(env)
    assert response.json()["provider"] == "openai"
    assert env.attempts == ["openai"]


def test_allowed_preference_wins_over_project_default(env):
    _policy(env, default_asr_engine="openai")
    assert _transcribe(env).json()["provider"] == "breeze"


def test_project_default_used_without_preference(env):
    _policy(env, default_asr_engine="openai")
    env.runtime.account_access.set_asr_provider(env.owner.id, "")
    assert _transcribe(env).json()["provider"] == "openai"


def test_fallback_and_deployment_default_stay_inside_project(env):
    _policy(env, allowed_asr_engines=["openai"])
    env.failing.add("openai")
    response = _transcribe(env)
    assert response.status_code == 200
    assert response.json()["provider"] == ""
    # 部署預設 breeze 與沒授權的 sensevoice 都不能當備援。
    assert env.attempts == ["openai"]


def test_project_without_batch_engines_refuses_implicit_requests(env):
    _policy(env, allowed_asr_engines=["gemini-live"])
    assert _transcribe(env).status_code == 403
    assert env.attempts == []


def test_taiwanese_route_uses_the_projects_engine(env):
    env.routes = ["zh", "nan"]
    _policy(env, taiwanese_asr_engine="openai")
    response = _transcribe(env)
    assert response.json()["provider"] == "openai"
    assert response.json()["language"] == "nan"
    assert env.attempts == ["openai"]
    # 台語判斷帶專案，Brain 才會用該專案的 Gemini 金鑰。
    assert env.heard_projects == ["p1"]


def test_taiwanese_engine_must_be_allowed(env):
    env.routes = ["zh", "nan"]
    _policy(env, allowed_asr_engines=["openai"])
    assert _transcribe(env).json()["provider"] == "openai"
    assert env.attempts == ["openai"]


def test_taiwanese_route_without_policy_keeps_breeze(env):
    env.routes = ["zh", "nan"]
    env.runtime.account_access.set_asr_provider(env.owner.id, "openai")
    assert _transcribe(env).json()["provider"] == "breeze"


def test_unreadable_project_means_no_project_policy(env):
    _policy(env, allowed_asr_engines=["openai"])
    # 讀不到的專案不會被套用，也不會讓請求失敗（跟語言分流一致）。
    assert _transcribe(env, project_id="someone-else").json()["provider"] == "breeze"


def test_embed_inherits_the_project_list(env):
    policy = _policy(env, allowed_asr_engines=["openai"], default_asr_engine="openai")
    scope = voice_policy.batch_asr_scope(env.runtime, None, policy, embed=True)
    assert scope.allowed == {"openai"}
    assert scope.preferred == "openai"
    assert scope.explicit == {"openai"}
    unrestricted = voice_policy.batch_asr_scope(env.runtime, None, None, embed=True)
    assert unrestricted.allowed == {"breeze"}
    assert unrestricted.explicit == frozenset()


# --- Uploaded media (process_media) ---------------------------------------


def test_media_job_without_project_is_unchanged(env):
    assert worker._media_asr_scope({"owner_user_id": env.owner.id}) == ("breeze", None)


def test_media_job_respects_project_policy(env):
    _policy(env, allowed_asr_engines=["openai", "sensevoice"])
    preferred, allowed = worker._media_asr_scope(
        {"owner_user_id": env.owner.id, "project_id": "p1"},
    )
    # 偏好與部署預設 breeze 都被專案擋掉、專案沒設預設：交給備援清單在 allowed 內挑。
    assert preferred is None
    assert allowed == {"openai"}
    _policy(env, allowed_asr_engines=["openai"], default_asr_engine="openai")
    assert worker._media_asr_scope(
        {"owner_user_id": env.owner.id, "project_id": "p1"},
    ) == ("openai", {"openai"})


def test_dispatch_passes_the_allowlist_to_transcribe(env, monkeypatch):
    seen = {}

    async def fake_transcribe(file_path, trace_id, preferred=None, **kwargs):
        seen.update(kwargs, preferred=preferred)
        return ingestion_audio.IngestionResult(
            content_type="audio_transcription", content="ok", provider="openai",
        )

    monkeypatch.setattr(ingestion_audio, "transcribe", fake_transcribe)
    asyncio.run(dispatcher.dispatch(
        "/tmp/clip.wav", "audio/wav", "t1", "openai",
        asr_allowed=frozenset({"openai"}),
    ))
    assert seen == {"preferred": "openai", "allowed_providers": {"openai"}}


# --- Streaming ASR ---------------------------------------------------------


def test_stream_request_outside_project_is_refused_even_for_admins(env):
    policy = _policy(env, allowed_asr_engines=["r2t2-live"])
    admin = CurrentAccount(
        user=SimpleNamespace(role=AccountRole.ADMIN, id="admin"),
        transport=AuthTransport.BEARER,
    )
    assert asr_stream._engine_for(env.account, "gemini-live", policy) == ""
    assert asr_stream._engine_for(env.account, "r2t2-live", policy) == "r2t2-live"
    assert asr_stream._engine_for(admin, "gemini-live", policy) == ""
    assert asr_stream._engine_for(admin, "gemini-live") == "gemini-live"


def test_stream_default_follows_preference_then_project(env):
    env.runtime.account_access.set_asr_provider(env.owner.id, "gemini-live")
    assert asr_stream._engine_for(env.account, None) == "gemini-live"
    policy = _policy(
        env, allowed_asr_engines=["r2t2-live", "breeze"],
        default_asr_engine="r2t2-live",
    )
    assert asr_stream._engine_for(env.account, None, policy) == "r2t2-live"
    # 選了批次引擎的人不會被專案預設換成串流。
    env.runtime.account_access.set_asr_provider(env.owner.id, "breeze")
    assert asr_stream._engine_for(env.account, None, policy) == ""


def test_stream_embed_uses_project_default_only_when_restricted(env):
    restricted = _policy(
        env, allowed_asr_engines=["r2t2-live"], default_asr_engine="r2t2-live",
    )
    assert asr_stream._engine_for(_embed(), None, restricted) == "r2t2-live"
    assert asr_stream._engine_for(_embed(), "r2t2-live", restricted) == ""
    loose = _policy(env, default_asr_engine="r2t2-live")
    assert asr_stream._engine_for(_embed(), None, loose) == ""


def test_stream_socket_refuses_engine_outside_project(env, monkeypatch):
    _policy(env, allowed_asr_engines=["r2t2-live"])
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    monkeypatch.setattr(
        asr_stream.websockets, "connect",
        MagicMock(side_effect=AssertionError("must not connect upstream")),
    )
    with TestClient(env.app) as client:
        with client.websocket_connect(
            "/api/v1/asr/stream?engine=gemini-live&project_id=p1",
            headers={"Authorization": f"Bearer {env.token}"},
        ) as ws:
            assert ws.receive_json() == {"type": "error", "code": "not_allowed"}


# --- TTS voice resolution --------------------------------------------------


def _resolve(env, current=None, provider="", voice="", project_id="p1"):
    return resolve_tts_voice(
        current or env.account, env.runtime,
        requested_provider=provider, requested_voice=voice,
        project_id=project_id,
    )


def test_tts_without_policy_is_unchanged(env):
    assert _resolve(env).resource_id == "index-a"
    assert _resolve(env, voice="cosy-a", project_id=None).runtime_key == "cosy-upstream"


def test_tts_voice_outside_project_is_403(env):
    _policy(env, allowed_tts_voices=["cosy-a"])
    with pytest.raises(HTTPException) as caught:
        _resolve(env, voice="index-a")
    assert caught.value.status_code == 403
    assert _resolve(env, voice="cosy-a").provider == "cosyvoice"


def test_tts_default_prefers_project_then_account_then_list(env):
    _policy(env, default_tts_voice="vox-a")
    assert _resolve(env).resource_id == "vox-a"
    _policy(env, allowed_tts_voices=["cosy-a", "index-a"])
    assert _resolve(env).resource_id == "index-a"
    _policy(env, allowed_tts_voices=["cosy-a"])
    assert _resolve(env).resource_id == "cosy-a"


def test_tts_policy_binds_unrestricted_admins_too(env):
    _policy(env, allowed_tts_voices=["cosy-a"])
    admin_user = env.runtime.users.create(
        username="unrestricted-admin", password_hash="unused", role=AccountRole.ADMIN,
        created_by=env.root.id,
    )
    admin = CurrentAccount(user=admin_user, transport=AuthTransport.BEARER)
    assert _resolve(env, admin).resource_id == "cosy-a"
    with pytest.raises(HTTPException) as caught:
        _resolve(env, admin, voice="index-a")
    assert caught.value.status_code == 403
    assert _resolve(env, admin, project_id=None) is None

    # ROOT 豁免不受專案清單限制
    root = CurrentAccount(user=env.root, transport=AuthTransport.BEARER)
    assert _resolve(env, root, voice="index-a").resource_id == "index-a"


def test_embed_inherits_project_voice_policy(env):
    _policy(env, allowed_tts_voices=["cosy-a"], default_tts_voice="cosy-a")
    authorized = _resolve(env, _embed())
    assert (authorized.provider, authorized.runtime_key) == ("cosyvoice", "cosy-upstream")
    with pytest.raises(HTTPException) as caught:
        _resolve(env, _embed(provider="indextts", voice="index-a"))
    assert caught.value.status_code == 403
    assert embed_tts_providers(
        _embed(provider="indextts", voice="index-a"), env.runtime,
        env.runtime.project_policies.get("p1"),
    ) == []
    assert embed_tts_providers(
        _embed(), env.runtime, env.runtime.project_policies.get("p1"),
    )[0]["voices"] == ["cosy-a"]


def test_embed_without_policy_is_unchanged(env):
    assert _resolve(env, _embed()) is None
    assert _resolve(env, _embed(provider="indextts", voice="index-a")).provider == "indextts"


def test_provider_listing_is_narrowed_by_project(env):
    policy = _policy(env, allowed_tts_voices=["cosy-a", "edge-a"], default_tts_voice="edge-a")
    listed = {
        item["id"]: (item["voices"], item["default_voice"])
        for item in scoped_tts_providers(env.account, env.runtime, policy)
    }
    assert listed == {
        "cosyvoice": (["cosy-a"], "cosy-a"),
        "edge-tts": (["edge-a"], "edge-a"),
    }


def test_edge_fallback_voice_follows_policy(env):
    assert tts_fallback_voice(env.runtime, None) == ""
    assert tts_fallback_voice(env.runtime, _policy(env, default_tts_voice="cosy-a")) == ""
    assert tts_fallback_voice(env.runtime, _policy(env, allowed_tts_voices=["cosy-a"])) is None
    assert tts_fallback_voice(
        env.runtime, _policy(env, allowed_tts_voices=["cosy-a", "edge-a"]),
    ) == "zh-TW-YunJheNeural"


# --- TTS service fallback --------------------------------------------------


def _ok(provider):
    return NormalizedTTSResult(
        audio_bytes=b"\x00", content_type="audio/mpeg", sample_rate=24000,
        provider=provider, route_kind="provider", route_target=provider,
        latency_ms=1.0,
    )


def _service():
    svc = TTSRouterService(TTSRouterConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        tts_indextts_url="http://index",
        edge_tts_enabled=True,
    ))
    svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("down"))  # type: ignore[method-assign]
    svc._edge.synthesize = MagicMock(return_value=_ok("edge-tts"))  # type: ignore[method-assign]
    return svc


def test_service_refuses_edge_fallback_when_policy_forbids_it():
    svc = _service()
    with pytest.raises(RuntimeError, match="Edge"):
        svc.synthesize(
            SynthesizeRequest(text="hi", voice_hint="x"),
            provider="indextts", edge_fallback_voice=None,
        )
    svc._edge.synthesize.assert_not_called()


def test_service_uses_the_projects_edge_voice_for_fallback():
    svc = _service()
    output = svc.synthesize(
        SynthesizeRequest(text="hi", voice_hint="x"),
        provider="indextts", edge_fallback_voice="zh-TW-YunJheNeural",
    )
    assert output.fallback
    assert svc._edge.synthesize.call_args.args[0].voice_hint == "zh-TW-YunJheNeural"


# --- TTS HTTP routes -------------------------------------------------------


class _FakeService:
    def __init__(self):
        self.calls: list[tuple] = []
        self.streams: list[str] = []
        # 這些 provider 的整段合成會失敗，看得出有沒有退回 Edge。
        self.failing = {"indextts", "cosyvoice"}
        self.edge_adapter = SimpleNamespace(
            enabled=True, synthesize_stream=self._stream,
        )
        self.voxcpm_adapter = SimpleNamespace(
            enabled=False, default_voice="voxcpm2-cosy-young-female-01",
            open_stream=self._voxcpm_stream,
        )
        # CosyVoice 預設關著：台語分流照舊退到 VoxCPM；要測 CosyVoice 的測試自己打開。
        self.cosyvoice_adapter = SimpleNamespace(
            enabled=False, default_voice="young-female-02",
        )
        self.gemini_adapter = SimpleNamespace(enabled=False)

    def _stream(self, request):
        self.streams.append(request.voice_hint)
        return iter([b"edge"])

    async def _voxcpm_stream(self, request, sample_rate=None):
        from app.providers.voxcpm_adapter import VoxCPMHTTPError

        self.calls.append(("voxcpm-stream", request.voice_hint, None))
        raise VoxCPMHTTPError(status_code=503, detail="GPU busy")

    def synthesize(self, request, *, provider="", edge_fallback_voice="", partners=()):
        self.calls.append((provider, request.voice_hint, edge_fallback_voice))
        for partner, partner_voice in partners:
            if provider in self.failing and partner not in self.failing:
                self.calls.append((partner, partner_voice, edge_fallback_voice))
                return SimpleNamespace(
                    result=_ok(partner), fallback=True, fallback_reason="down",
                )
        if provider not in self.failing:
            return SimpleNamespace(
                result=_ok(provider), fallback=False, fallback_reason="",
            )
        if edge_fallback_voice is None:
            raise RuntimeError("TTS provider 失敗，專案不允許改用 Edge-TTS")
        return SimpleNamespace(
            result=_ok("edge-tts"), fallback=True, fallback_reason="down",
        )


@pytest.fixture
def tts_client(env, monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(tts, "_get_service", lambda: service)

    async def plain(text):
        return text

    monkeypatch.setattr(tts, "prepare_tts_text_async", plain)
    monkeypatch.setattr(tts, "record_usage_event", lambda **kw: None)
    monkeypatch.setenv("TTS_INDEXTTS_URL", "")
    app = FastAPI()
    app.include_router(tts.router)
    with TestClient(app) as client:
        client.service = service
        client.headers.update({"Authorization": f"Bearer {env.token}"})
        yield client


def _stream(client, **body):
    return client.post("/api/v1/tts/stream", json={"text": "你好", "project_id": "p1", **body})


def test_stream_without_policy_still_falls_back_to_edge(env, tts_client):
    response = _stream(tts_client, provider="indextts", voice="index-a")
    assert response.status_code == 200
    assert tts_client.service.streams == ["index-a"]


def test_stream_refuses_silent_edge_switch_when_project_forbids_it(env, tts_client):
    _policy(env, allowed_tts_voices=["index-a", "cosy-a"])
    response = _stream(tts_client, provider="indextts", voice="index-a")
    assert response.status_code == 502
    assert tts_client.service.streams == []
    assert tts_client.service.calls == [("indextts", "index-a", None)]
    cosy = _stream(tts_client, provider="cosyvoice", voice="cosy-a")
    assert cosy.status_code == 502
    assert tts_client.service.calls[-1] == ("cosyvoice", "cosy-upstream", None)


def test_stream_falls_back_to_the_projects_edge_voice(env, tts_client):
    _policy(env, allowed_tts_voices=["index-a", "edge-a"])
    assert _stream(tts_client, provider="indextts", voice="index-a").status_code == 200
    assert tts_client.service.streams == ["zh-TW-YunJheNeural"]


def test_stream_rejects_voice_outside_project(env, tts_client):
    _policy(env, allowed_tts_voices=["cosy-a"])
    assert _stream(tts_client, provider="indextts", voice="index-a").status_code == 403


def test_taiwanese_override_without_policy_uses_cosyvoice_default(
    env, tts_client, monkeypatch,
):
    # VH-384：台語改用 CosyVoice（會把漢字轉台文），聲音用部署預設。
    async def routes(*args):
        return ["zh", "nan"]

    monkeypatch.setattr(tts.language_routes_mod, "effective_routes", routes)
    tts_client.service.cosyvoice_adapter.enabled = True
    _stream(tts_client, provider="indextts", voice="index-a", speech_language="nan")
    assert tts_client.service.calls[0][:2] == ("cosyvoice", "")


def test_taiwanese_override_keeps_the_voice_when_no_taiwanese_engine_runs(
    env, tts_client, monkeypatch,
):
    async def routes(*args):
        return ["zh", "nan"]

    monkeypatch.setattr(tts.language_routes_mod, "effective_routes", routes)
    _stream(tts_client, provider="indextts", voice="index-a", speech_language="nan")
    # CosyVoice、VoxCPM 都沒啟用：不換引擎，照原本的聲音。
    assert "cosyvoice" not in [call[0] for call in tts_client.service.calls]
    assert tts_client.service.streams == ["index-a"]


def test_taiwanese_override_stays_inside_project(env, tts_client, monkeypatch):
    async def routes(*args):
        return ["zh", "nan"]

    monkeypatch.setattr(tts.language_routes_mod, "effective_routes", routes)
    tts_client.service.cosyvoice_adapter.enabled = True
    _policy(env, allowed_tts_voices=["index-a", "vox-a", "cosy-a"])
    _stream(tts_client, provider="indextts", voice="index-a", speech_language="nan")
    # 清單裡同時有 CosyVoice 與 VoxCPM 的聲音：先用 CosyVoice（假服務的 CosyVoice 會失敗，只看選了誰）。
    assert tts_client.service.calls[0][:2] == ("cosyvoice", "cosy-upstream")

    tts_client.service.calls.clear()
    _policy(env, allowed_tts_voices=["index-a", "vox-a"])
    _stream(tts_client, provider="indextts", voice="index-a", speech_language="nan")
    # 清單裡唯一的台語聲音在沒啟用的 VoxCPM 上：不換過去再失敗，照原本的聲音唸。
    assert tts_client.service.calls == [("indextts", "index-a", None)]

    tts_client.service.calls.clear()
    _policy(env, allowed_tts_voices=["index-a"])
    _stream(tts_client, provider="indextts", voice="index-a", speech_language="nan")
    # 專案沒有台語可用的聲音：不換引擎，照一般流程用專案允許的聲音。
    assert tts_client.service.calls == [("indextts", "index-a", None)]


def test_speech_cache_key_is_scoped_only_for_restricted_projects(env, tts_client, monkeypatch):
    keys: list[str] = []

    async def cache_get(key):
        keys.append(key)
        return None

    async def cache_put(*args, **kwargs):
        pass

    monkeypatch.setattr(tts, "get_tts_config", lambda: SimpleNamespace(
        tts_cache_enabled=True, tts_cache_ttl_seconds=60,
    ))
    monkeypatch.setattr(tts, "cache_get", cache_get)
    monkeypatch.setattr(tts, "cache_put", cache_put)
    tts_client.service.failing.clear()
    body = {"input": "你好", "voice": "index-a", "project_id": "p1"}
    assert tts_client.post("/v1/audio/speech", json=body).status_code == 200
    _policy(env, allowed_tts_voices=["index-a"])
    assert tts_client.post("/v1/audio/speech", json=body).status_code == 200
    assert keys[0] == make_cache_key("你好", "index-a", "indextts")
    assert keys[1] == make_cache_key(
        "你好", "index-a", "indextts", scope="project:p1",
    )
    assert tts_client.service.calls[-1] == ("indextts", "index-a", None)


@pytest.fixture
def indextts_up(monkeypatch, request):
    """IndexTTS configured; records which character the stream was opened with."""
    from fastapi.responses import StreamingResponse

    from app.config import get_tts_config

    monkeypatch.setenv("TTS_INDEXTTS_URL", "http://indextts.test")
    monkeypatch.setenv("TTS_INDEXTTS_DEFAULT_CHARACTER", "hayley")
    get_tts_config.cache_clear()
    request.addfinalizer(get_tts_config.cache_clear)
    opened: list[str] = []

    async def fake_proxy(*, indextts_stream_url, text, character):
        opened.append(character)
        return StreamingResponse(iter([b"RIFF"]), media_type="audio/wav")

    monkeypatch.setattr(tts, "_proxy_indextts_stream", fake_proxy)
    return opened


def test_mandarin_and_english_use_indextts_when_no_voice_is_chosen(env, tts_client, indextts_up):
    # VH-384：國語、英文 → IndexTTS。沒指定引擎或聲音時依語言決定，不跟著帳號預設走。
    # 帳號預設本來就是 IndexTTS 的聲音：照用。
    response = _stream(tts_client, language="zh")
    assert response.headers["X-TTS-Provider"] == "indextts"
    assert indextts_up == ["index-a"]

    # 專案預設是 Edge：國語、英文改用專案清單裡的 IndexTTS 聲音。
    indextts_up.clear()
    _policy(env, allowed_tts_voices=["edge-a", "index-a"], default_tts_voice="edge-a")
    for language in ("zh", "en"):
        response = _stream(tts_client, language=language)
        assert response.status_code == 200
        assert response.headers["X-TTS-Provider"] == "indextts"
    assert indextts_up == ["index-a", "index-a"]


def test_an_explicit_engine_is_kept_for_mandarin(env, tts_client, indextts_up):
    response = _stream(tts_client, provider="edge-tts", voice="edge-a", language="zh")
    assert response.headers["X-TTS-Provider"] == "edge-tts"
    assert indextts_up == []


def test_a_selected_taiwanese_language_switches_typed_turns(env, tts_client, monkeypatch):
    # 使用者在介面選台語、但用打字輸入：沒有 ASR 的 speech_language，看 language。
    async def routes(*args):
        return ["zh", "nan"]

    monkeypatch.setattr(tts.language_routes_mod, "effective_routes", routes)
    tts_client.service.cosyvoice_adapter.enabled = True
    tts_client.service.failing.discard("cosyvoice")
    response = _stream(tts_client, provider="edge-tts", voice="edge-a", language="nan")
    assert response.headers["X-TTS-Provider"] == "cosyvoice"
    assert tts_client.service.calls[0][:2] == ("cosyvoice", "")


def test_taiwanese_cosyvoice_outage_switches_to_voxcpm_in_the_same_voice(
    env, tts_client, monkeypatch,
):
    async def routes(*args):
        return ["zh", "nan"]

    monkeypatch.setattr(tts.language_routes_mod, "effective_routes", routes)
    tts_client.service.cosyvoice_adapter.enabled = True
    tts_client.service.voxcpm_adapter.enabled = True
    response = _stream(tts_client, provider="indextts", voice="index-a", speech_language="nan")
    assert response.status_code == 200
    # 假服務的 CosyVoice 一定失敗：先換 VoxCPM 的同名聲音，不是 Edge。
    assert tts_client.service.calls == [
        ("cosyvoice", "", ""),
        ("voxcpm", "voxcpm2-cosy-young-female-02", ""),
    ]
    assert response.headers["X-TTS-Provider"] == "voxcpm"
    assert tts_client.service.streams == []


def test_taiwanese_voxcpm_outage_switches_to_cosyvoice(env, tts_client, monkeypatch):
    async def routes(*args):
        return ["zh", "nan"]

    monkeypatch.setattr(tts.language_routes_mod, "effective_routes", routes)
    tts_client.service.cosyvoice_adapter.enabled = True
    tts_client.service.voxcpm_adapter.enabled = True
    tts_client.service.failing = {"indextts"}
    response = _stream(tts_client, provider="voxcpm", voice="vox-a", speech_language="nan")
    assert response.status_code == 200
    # vox-upstream 不是 voxcpm2-cosy-* 系列，對不到同名聲音：CosyVoice 用它的預設。
    assert tts_client.service.calls == [
        ("voxcpm-stream", "vox-upstream", None),
        ("cosyvoice", "", ""),
    ]
    assert response.headers["X-TTS-Provider"] == "cosyvoice"


def test_mandarin_turns_do_not_get_a_taiwanese_partner(env, tts_client, monkeypatch):
    tts_client.service.cosyvoice_adapter.enabled = True
    tts_client.service.voxcpm_adapter.enabled = True
    response = _stream(tts_client, provider="cosyvoice", voice="cosy-a")
    assert response.status_code == 200
    # 華語指定 CosyVoice 失敗照舊退 Edge，不換成照字唸的 VoxCPM。
    assert [call[0] for call in tts_client.service.calls] == ["cosyvoice"]
