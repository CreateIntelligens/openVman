"""The second IndexTTS server (indextts-nurse): opt-in engine beside the .35 one."""

from __future__ import annotations

import asyncio
import types
from unittest.mock import ANY, MagicMock

import httpx
import pytest

from app import health_payloads, system_resources
from app.auth.dependencies import AuthTransport, CurrentAccount
from app.auth.models import AccountRole, ResourceType
from app.auth.runtime import build_auth_runtime
from app.auth.voice_access import deployment_default_voice, resolve_tts_voice
from app.config import TTSRouterConfig
from app.providers import voice_catalog
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.providers.indextts_adapter import (
    INDEXTTS_NURSE_PROVIDER_NAME,
    IndexTTSAdapter,
    indextts_nurse_default_character,
)
from app.service import TTSRouterService
from app.tts_cache import make_cache_key

_PRIMARY = "http://index-primary:8011"
_NURSE = "http://nurse-tts:8001"


def _config(**overrides) -> TTSRouterConfig:
    values = {
        "tts_indextts_url": _PRIMARY,
        "tts_indextts_default_character": "hayley",
        "tts_indextts_nurse_url": _NURSE,
        "gateway_internal_token": "test-internal-token",
        "edge_tts_enabled": True,
        "edge_tts_voice": "zh-TW-HsiaoChenNeural",
        **overrides,
    }
    return TTSRouterConfig(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def _ok(provider: str) -> NormalizedTTSResult:
    return NormalizedTTSResult(
        audio_bytes=b"RIFF" + b"\x00" * 100,
        content_type="audio/wav",
        sample_rate=16000,
        provider=provider,
        route_kind="provider",
        route_target=provider,
        latency_ms=1.0,
    )


# --- config ---------------------------------------------------------------


def test_config_reads_nurse_env_vars(monkeypatch):
    monkeypatch.setenv("TTS_INDEXTTS_NURSE_URL", _NURSE)
    monkeypatch.setenv("TTS_INDEXTTS_NURSE_DEFAULT_CHARACTER", "jay")

    cfg = TTSRouterConfig(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert cfg.tts_indextts_nurse_url == _NURSE
    assert cfg.tts_indextts_nurse_default_character == "jay"


def test_config_nurse_defaults_to_unset_with_hayley(monkeypatch):
    monkeypatch.delenv("TTS_INDEXTTS_NURSE_URL", raising=False)
    monkeypatch.delenv("TTS_INDEXTTS_NURSE_DEFAULT_CHARACTER", raising=False)

    cfg = TTSRouterConfig(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert cfg.tts_indextts_nurse_url == ""
    assert cfg.tts_indextts_nurse_default_character == "hayley"
    assert IndexTTSAdapter.for_nurse(cfg).enabled is False


def test_blank_nurse_default_character_still_means_hayley():
    # compose 把沒設的變數展開成空字串時也不能變成「沒有角色」。
    cfg = _config(tts_indextts_nurse_default_character="  ")

    assert indextts_nurse_default_character(cfg) == "hayley"


# --- adapter --------------------------------------------------------------


def test_nurse_synthesis_goes_to_nurse_url_without_internal_token():
    adapter = IndexTTSAdapter.for_nurse(_config())
    adapter._opencc_t2s = None
    adapter._client.post = MagicMock(return_value=httpx.Response(
        200, content=b"wav", headers={"content-type": "audio/wav"},
    ))

    result = adapter.synthesize(
        SynthesizeRequest(text="你好", voice_hint="indextts-nurse:healthy2"),
    )

    adapter._client.post.assert_called_once_with(
        f"{_NURSE}/tts",
        json={"text": "你好", "character": "healthy2"},
        headers={},
        timeout=ANY,
    )
    assert (result.provider, result.route_target) == (
        INDEXTTS_NURSE_PROVIDER_NAME, INDEXTTS_NURSE_PROVIDER_NAME,
    )


def test_nurse_adapter_uses_its_own_default_character():
    adapter = IndexTTSAdapter.for_nurse(
        _config(tts_indextts_default_character="primary-only",
                tts_indextts_nurse_default_character="jay"),
    )
    adapter._opencc_t2s = None
    adapter._client.post = MagicMock(return_value=httpx.Response(200, content=b"wav"))

    adapter.synthesize(SynthesizeRequest(text="你好"))

    assert adapter._client.post.call_args.kwargs["json"]["character"] == "jay"


def test_primary_adapter_is_unchanged():
    adapter = IndexTTSAdapter(_config())
    adapter._opencc_t2s = None
    adapter._client.post = MagicMock(return_value=httpx.Response(200, content=b"wav"))

    result = adapter.synthesize(SynthesizeRequest(text="你好", voice_hint="hayley"))

    adapter._client.post.assert_called_once_with(
        f"{_PRIMARY}/tts",
        json={"text": "你好", "character": "hayley"},
        headers={"X-Internal-Token": "test-internal-token"},
        timeout=ANY,
    )
    assert result.provider == "indextts"


# --- routing / fallback chain ---------------------------------------------


def test_nurse_is_not_in_the_default_chain():
    svc = TTSRouterService(_config())

    targets = [route.target for route in svc.build_chain()]

    assert "indextts" in targets
    assert INDEXTTS_NURSE_PROVIDER_NAME not in targets


def test_auto_synthesis_never_falls_back_to_nurse():
    svc = TTSRouterService(_config())
    svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
    svc._indextts_nurse.synthesize = MagicMock(return_value=_ok("indextts-nurse"))  # type: ignore[method-assign]
    svc._edge.synthesize = MagicMock(return_value=_ok("edge-tts"))  # type: ignore[method-assign]

    output = svc.synthesize(SynthesizeRequest(text="你好"))

    assert output.result.provider == "edge-tts"
    svc._indextts_nurse.synthesize.assert_not_called()


def test_targeted_synthesis_uses_nurse():
    svc = TTSRouterService(_config())
    svc._indextts.synthesize = MagicMock(return_value=_ok("indextts"))  # type: ignore[method-assign]
    svc._indextts_nurse.synthesize = MagicMock(return_value=_ok("indextts-nurse"))  # type: ignore[method-assign]

    output = svc.synthesize(
        SynthesizeRequest(text="你好", voice_hint="hayley"),
        provider=INDEXTTS_NURSE_PROVIDER_NAME,
    )

    assert output.result.provider == INDEXTTS_NURSE_PROVIDER_NAME
    svc._indextts.synthesize.assert_not_called()


def test_project_engine_order_may_name_nurse():
    svc = TTSRouterService(_config())

    targets = [
        route.target
        for route in svc.build_chain(order=(INDEXTTS_NURSE_PROVIDER_NAME, "edge-tts"))
    ]

    assert targets == [INDEXTTS_NURSE_PROVIDER_NAME, "edge-tts"]


def test_unconfigured_nurse_cannot_be_targeted():
    svc = TTSRouterService(_config(tts_indextts_nurse_url=""))

    targets = [route.target for route in svc.build_chain(include_opt_in=True)]

    assert INDEXTTS_NURSE_PROVIDER_NAME not in targets


def test_default_taiwanese_order_leaves_nurse_out(monkeypatch):
    monkeypatch.delenv("TTS_TAIWANESE_FALLBACK_ORDER", raising=False)

    cfg = TTSRouterConfig(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert INDEXTTS_NURSE_PROVIDER_NAME not in cfg.tts_taiwanese_fallback_order


# --- cache ----------------------------------------------------------------


def test_cache_keys_differ_between_the_two_servers():
    # 兩台都有 hayley；授權後送上游的都是 "hayley"，只能靠 provider 分開。
    assert make_cache_key("你好", "hayley", "indextts") != make_cache_key(
        "你好", "hayley", INDEXTTS_NURSE_PROVIDER_NAME,
    )


# --- catalog and resources ------------------------------------------------


class _FakeVoicesClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []

    async def get(self, url, timeout=None, headers=None, follow_redirects=None):
        self.calls.append((url, headers))
        voices = {
            f"{_PRIMARY}/audio/voices": {"jay": [], "hayley": []},
            f"{_NURSE}/audio/voices": {"hayley": [], "healthy2": []},
        }[url]
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: voices)


@pytest.fixture
def voices_client(monkeypatch):
    client = _FakeVoicesClient()
    monkeypatch.setattr(
        voice_catalog, "_http", types.SimpleNamespace(get=lambda: client),
    )
    return client


def _catalog_cfg(**overrides):
    values = {
        "tts_indextts_url": _PRIMARY,
        "tts_indextts_default_character": "hayley",
        "tts_indextts_nurse_url": _NURSE,
        "tts_indextts_nurse_default_character": "hayley",
        "gateway_internal_token": "test-internal-token",
        "tts_voxcpm_url": "",
        "tts_cosyvoice_url": "",
        "tts_gcp_enabled": False,
        "tts_aws_enabled": False,
        "tts_gemini_url": "",
        "edge_tts_enabled": False,
        **overrides,
    }
    return types.SimpleNamespace(**values)


def test_catalog_lists_nurse_with_prefixed_voice_ids(voices_client):
    providers = asyncio.run(voice_catalog.build_tts_provider_catalog(_catalog_cfg()))
    by_id = {provider["id"]: provider for provider in providers}

    assert by_id["indextts"]["voices"] == ["jay", "hayley"]
    nurse = by_id[INDEXTTS_NURSE_PROVIDER_NAME]
    assert nurse["name"] == "IndexTTS（nurse24h）"
    assert nurse["default_voice"] == "indextts-nurse:hayley"
    assert nurse["voices"] == ["indextts-nurse:hayley", "indextts-nurse:healthy2"]
    assert nurse["voice_items"] == [
        {"id": "indextts-nurse:hayley", "label": "Hayley"},
        {"id": "indextts-nurse:healthy2", "label": "healthy2"},
    ]
    assert set(nurse["voices"]).isdisjoint(by_id["indextts"]["voices"])
    # 內部 token 只送自家那台。
    assert dict(voices_client.calls)[f"{_NURSE}/audio/voices"] is None


def test_catalog_omits_nurse_when_url_is_empty(voices_client):
    providers = asyncio.run(voice_catalog.build_tts_provider_catalog(
        _catalog_cfg(tts_indextts_nurse_url=""),
    ))

    assert INDEXTTS_NURSE_PROVIDER_NAME not in {provider["id"] for provider in providers}
    assert all(_NURSE not in url for url, _ in voices_client.calls)


@pytest.fixture
def runtime(tmp_path):
    runtime = build_auth_runtime(_config(
        env="dev",
        session_jwt_secret="nurse-test-secret-at-least-32-chars",
        auth_database_path=str(tmp_path / "accounts.db"),
    ))
    runtime.users.create_root(username="ai360", password_hash="unused")
    return runtime


def _sync(runtime, cfg) -> None:
    asyncio.run(system_resources.sync_system_resources(runtime, cfg))


def test_sync_registers_both_servers_without_collision(runtime, voices_client):
    _sync(runtime, _catalog_cfg())

    primary = runtime.resources.get(ResourceType.CUSTOM_VOICE, "hayley")
    nurse = runtime.resources.get(ResourceType.CUSTOM_VOICE, "indextts-nurse:hayley")
    assert primary is not None and '"provider":"indextts"' in primary.metadata_json
    assert nurse is not None
    assert '"provider":"indextts-nurse"' in nurse.metadata_json
    assert '"runtime_key":"hayley"' in nurse.metadata_json


def test_sync_skips_nurse_when_url_is_empty(runtime, voices_client):
    _sync(runtime, _catalog_cfg(tts_indextts_nurse_url=""))

    ids = {
        record.resource_id
        for record in runtime.resources.list_by_type(ResourceType.CUSTOM_VOICE)
    }
    assert not any(voice.startswith("indextts-nurse:") for voice in ids)


def test_granted_nurse_voice_resolves_to_nurse_with_upstream_name(runtime, voices_client):
    _sync(runtime, _catalog_cfg())
    for resource_type, resource_id in (
        (ResourceType.PROJECT, "p1"), (ResourceType.AVATAR_CHARACTER, "a1"),
    ):
        runtime.resources.upsert_system_resource(
            resource_type=resource_type, resource_id=resource_id,
        )
    root = runtime.users.get_by_username("ai360")
    user = runtime.users.create(
        username="nurse-user", password_hash="unused", role=AccountRole.USER,
        created_by=root.id,
        grants=[
            (ResourceType.PROJECT, "p1"),
            (ResourceType.AVATAR_CHARACTER, "a1"),
            (ResourceType.CUSTOM_VOICE, "hayley"),
            (ResourceType.CUSTOM_VOICE, "indextts-nurse:hayley"),
        ],
        defaults=("p1", "a1", "indextts-nurse", "indextts-nurse:hayley"),
    )
    current = CurrentAccount(user=user, transport=AuthTransport.BEARER)

    nurse = resolve_tts_voice(
        current, runtime,
        requested_provider="indextts-nurse", requested_voice="indextts-nurse:hayley",
    )
    primary = resolve_tts_voice(
        current, runtime, requested_provider="indextts", requested_voice="hayley",
    )

    assert nurse is not None and primary is not None
    assert (nurse.provider, nurse.runtime_key) == (INDEXTTS_NURSE_PROVIDER_NAME, "hayley")
    assert (primary.provider, primary.runtime_key) == ("indextts", "hayley")
    assert nurse.cache_scope != primary.cache_scope
    # 帳號預設選了 nurse 的聲音：沒指定時就用它，這是帳號自己選的。
    default = resolve_tts_voice(current, runtime, requested_provider="", requested_voice="")
    assert default is not None
    assert (default.provider, default.runtime_key) == (INDEXTTS_NURSE_PROVIDER_NAME, "hayley")


def test_deployment_default_voice_matches_the_prefixed_id(monkeypatch):
    from app.auth import voice_access

    monkeypatch.setattr(voice_access, "get_tts_config", lambda: _config(
        tts_indextts_nurse_default_character="jay",
    ))

    assert deployment_default_voice(INDEXTTS_NURSE_PROVIDER_NAME) == "indextts-nurse:jay"
    assert deployment_default_voice("indextts") == "hayley"


# --- health ---------------------------------------------------------------


def test_health_probe_is_disabled_without_url():
    result = asyncio.run(health_payloads.probe_indextts_nurse_health(
        MagicMock(), _config(tts_indextts_nurse_url=""),
    ))

    assert result == {"status": "disabled"}


def test_health_probe_uses_plain_health_endpoint():
    requested: list[str] = []

    class Client:
        async def get(self, url, headers=None, timeout=None):
            requested.append(url)
            return types.SimpleNamespace(
                status_code=200, json=lambda: {"status": "healthy"},
            )

    result = asyncio.run(health_payloads.probe_indextts_nurse_health(Client(), _config()))

    assert requested == [f"{_NURSE}/health"]
    assert result["status"] == "ready"
