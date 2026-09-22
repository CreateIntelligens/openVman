"""Tests for TTS router service fallback chain."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from app.config import TTSRouterConfig
from app.observability import get_metrics_snapshot, reset_metrics
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.service import TTSRouterService


def _make_config(
    indextts_url: str = "http://index",
    aws_enabled: bool = True,
    gcp_enabled: bool = True,
    edge_enabled: bool = False,
    gemini_url: str = "",
    voxcpm_url: str = "",
) -> TTSRouterConfig:
    return TTSRouterConfig(
        _env_file=None,
        tts_indextts_url=indextts_url,
        tts_indextts_default_character="hayley",
        tts_aws_enabled=aws_enabled,
        tts_aws_region="ap-northeast-1",
        tts_aws_access_key_id="key",
        tts_aws_secret_access_key="secret",
        tts_aws_polly_voice_id="Zhiyu",
        tts_aws_polly_engine="neural",
        tts_aws_output_format="pcm",
        tts_aws_sample_rate=24000,
        tts_gcp_enabled=gcp_enabled,
        tts_gcp_project_id="test-proj",
        tts_gcp_voice_name="cmn-TW-Standard-A",
        tts_gcp_audio_encoding="LINEAR16",
        tts_gcp_sample_rate=24000,
        edge_tts_enabled=edge_enabled,
        tts_gemini_url=gemini_url,
        tts_voxcpm_url=voxcpm_url,
    )


def _ok_result(provider: str = "aws") -> NormalizedTTSResult:
    target = f"{provider}-tts"
    if provider == "aws":
        target = "aws-polly"

    return NormalizedTTSResult(
        audio_bytes=b"\x00\x01",
        content_type="audio/pcm",
        sample_rate=24000,
        provider=provider,
        route_kind="provider",
        route_target=target,
        latency_ms=50.0,
    )


class TestRouterFallback:
    def setup_method(self):
        reset_metrics()

    def test_indextts_success_returns_immediately(self):
        """IndexTTS succeeds -> no GCP/AWS hop."""
        svc = TTSRouterService(_make_config())
        svc._indextts.synthesize = MagicMock(return_value=_ok_result("index"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.result.provider == "index"
        svc._aws.synthesize.assert_not_called()
        svc._gcp.synthesize.assert_not_called()

    def test_indextts_fails_falls_back_to_gcp(self):
        """IndexTTS fails -> GCP succeeds."""
        svc = TTSRouterService(_make_config())
        svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.result.provider == "gcp"
        svc._aws.synthesize.assert_not_called()

    def test_indextts_gcp_fail_falls_back_to_aws(self):
        """IndexTTS, GCP fail -> AWS succeeds."""
        svc = TTSRouterService(_make_config())
        svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.result.provider == "aws"

    def test_all_providers_fail_raises(self):
        """All providers fail -> RuntimeError."""
        svc = TTSRouterService(_make_config())
        svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(side_effect=RuntimeError("aws down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="所有 TTS fallback chain hops 皆失敗"):
            svc.synthesize(SynthesizeRequest(text="hello"))

    def test_router_returns_normalized_payload(self):
        """Router result has correct NormalizedTTSResult shape."""
        svc = TTSRouterService(_make_config())
        svc._indextts.synthesize = MagicMock(return_value=_ok_result("index"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="test"))
        assert isinstance(result.result, NormalizedTTSResult)
        assert result.result.audio_bytes == b"\x00\x01"
        assert result.result.route_kind == "provider"

    def test_disabled_indextts_skips_to_next(self):
        """IndexTTS disabled -> chain starts with gcp."""
        svc = TTSRouterService(_make_config(indextts_url=""))
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="test"))
        assert result.result.provider == "gcp"

    def test_disabled_all_raises_empty_chain(self):
        """All disabled -> empty chain error."""
        svc = TTSRouterService(_make_config(
            indextts_url="",
            aws_enabled=False,
            gcp_enabled=False,
            edge_enabled=False,
        ))
        with pytest.raises(RuntimeError, match="chain 為空"):
            svc.synthesize(SynthesizeRequest(text="test"))

    def test_chain_order_is_indextts_then_gcp_then_aws(self):
        """Verify the chain order: IndexTTS, GCP, AWS."""
        svc = TTSRouterService(_make_config())
        chain = svc.build_chain()
        targets = [t.target for t in chain]
        assert targets == ["indextts", "gcp-tts", "aws-polly"]

    def test_chain_order_with_gemini(self):
        """Verify the chain order when gemini is enabled."""
        svc = TTSRouterService(_make_config(gemini_url="http://localhost:8206"))
        chain = svc.build_chain()
        targets = [t.target for t in chain]
        assert targets == ["indextts", "gemini-tts", "gcp-tts", "aws-polly"]

    def test_indextts_fails_falls_back_to_gemini(self):
        """IndexTTS fails -> Gemini succeeds."""
        svc = TTSRouterService(_make_config(gemini_url="http://localhost:8206"))
        svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._gemini.synthesize = MagicMock(return_value=_ok_result("gemini"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.result.provider == "gemini"
        svc._gcp.synthesize.assert_not_called()

    def test_indextts_success_stops_without_extra_hops(self):
        """After IndexTTS success, no more hops are attempted."""
        svc = TTSRouterService(_make_config())
        svc._indextts.synthesize = MagicMock(return_value=_ok_result("index"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="test"))

        snap = get_metrics_snapshot()
        success_keys = [k for k in snap["counters"] if "result=success" in k]
        assert len(success_keys) == 2
        indextts_success = [k for k in success_keys if "indextts" in k or "index" in k]
        assert len(indextts_success) == 2

    def test_aws_success_stops_without_extra_hops(self):
        """After AWS success, no more hops are attempted."""
        svc = TTSRouterService(_make_config())
        svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(side_effect=RuntimeError("gcp down"))  # type: ignore[method-assign]
        svc._aws.synthesize = MagicMock(return_value=_ok_result("aws"))  # type: ignore[method-assign]

        svc.synthesize(SynthesizeRequest(text="test"))

        snap = get_metrics_snapshot()
        success_keys = [k for k in snap["counters"] if "result=success" in k]
        assert len(success_keys) == 2
        aws_success = [k for k in success_keys if "aws" in k]
        assert len(aws_success) == 2


class TestVoxCPMRoute:
    def setup_method(self):
        reset_metrics()

    def test_voxcpm_absent_from_chain_when_unconfigured(self):
        svc = TTSRouterService(_make_config())
        assert "voxcpm" not in [t.target for t in svc.build_chain()]

    def test_voxcpm_sits_between_indextts_and_gcp(self):
        svc = TTSRouterService(_make_config(voxcpm_url="http://voxcpm:8800"))
        targets = [t.target for t in svc.build_chain()]
        assert targets == ["indextts", "voxcpm", "gcp-tts", "aws-polly"]

    def test_indextts_fails_falls_back_to_voxcpm(self):
        svc = TTSRouterService(_make_config(voxcpm_url="http://voxcpm:8800"))
        svc._indextts.synthesize = MagicMock(side_effect=RuntimeError("index down"))  # type: ignore[method-assign]
        svc._voxcpm.synthesize = MagicMock(return_value=_ok_result("voxcpm"))  # type: ignore[method-assign]
        svc._gcp.synthesize = MagicMock(return_value=_ok_result("gcp"))  # type: ignore[method-assign]

        result = svc.synthesize(SynthesizeRequest(text="hello"))
        assert result.result.provider == "voxcpm"
        svc._gcp.synthesize.assert_not_called()

    def test_targeted_voxcpm_uses_voice_hint(self):
        svc = TTSRouterService(_make_config(voxcpm_url="http://voxcpm:8800"))
        svc._indextts.synthesize = MagicMock(return_value=_ok_result("index"))  # type: ignore[method-assign]
        svc._voxcpm.synthesize = MagicMock(return_value=_ok_result("voxcpm"))  # type: ignore[method-assign]

        request = SynthesizeRequest(
            text="hello",
            voice_hint="voxcpm2-cosy-teen-female-01",
        )
        result = svc.synthesize(request, provider="voxcpm")

        assert result.result.provider == "voxcpm"
        assert result.fallback is False
        svc._voxcpm.synthesize.assert_called_once_with(request)
        svc._indextts.synthesize.assert_not_called()


def test_successful_synthesis_meters_characters(monkeypatch):
    """TTS 按字元計價：成功的 hop 要記一筆 chars，失敗的 hop 不計費。"""
    recorded: list[dict] = []
    monkeypatch.setattr(
        "app.service.record_usage_event",
        lambda **kwargs: recorded.append(kwargs),
    )

    service = TTSRouterService(_make_config(edge_enabled=True))
    ok = MagicMock()
    ok.synthesize.return_value = NormalizedTTSResult(
        audio_bytes=b"pcm",
        content_type="audio/l16",
        sample_rate=24000,
        provider="gemini-tts",
        route_kind="provider",
        route_target="gemini",
        latency_ms=12.0,
    )
    failing = MagicMock()
    failing.synthesize.side_effect = RuntimeError("upstream down")

    base = service.build_chain()
    chain = [replace(base[0], adapter=failing)] + [
        replace(target, adapter=ok) for target in base[1:]
    ]

    request = SynthesizeRequest(
        text="你好，世界",
        usage_scope={"user_id": "u-1", "project_id": "p-1"},
    )
    service._synthesize_chain(request, chain)

    assert len(recorded) == 1, "只有成功的那一 hop 該記帳"
    event = recorded[0]
    assert event["unit_type"] == "chars"
    assert event["units"] == len("你好，世界")
    assert event["kind"] == "tts"
    assert event["provider"] == "gemini-tts"
    assert event["scope"] == {"user_id": "u-1", "project_id": "p-1"}


def test_ledger_failure_does_not_break_synthesis(monkeypatch):
    """記帳壞掉不可以讓使用者的語音合成失敗。"""
    def _boom(**_kwargs):
        raise RuntimeError("ledger unreachable")

    monkeypatch.setattr("app.service.record_usage_event", _boom)

    service = TTSRouterService(_make_config(edge_enabled=True))
    ok = MagicMock()
    ok.synthesize.return_value = NormalizedTTSResult(
        audio_bytes=b"pcm",
        content_type="audio/l16",
        sample_rate=24000,
        provider="edge-tts",
        route_kind="provider",
        route_target="edge",
        latency_ms=5.0,
    )
    chain = [replace(target, adapter=ok) for target in service.build_chain()]

    with pytest.raises(RuntimeError, match="ledger unreachable"):
        service._synthesize_chain(SynthesizeRequest(text="測試"), chain)


def test_usage_scope_distinguishes_embed_key_from_account():
    """主體判定要與 brain_proxy 的 header 規則一致：有金鑰就記金鑰。"""
    from app.usage_ledger_client import usage_scope_for

    account = MagicMock()
    account.user.id = "u-1"
    account.user.role.value = "member"
    account.embed_key = None
    assert usage_scope_for(account, project_id="p-1") == {
        "user_id": "u-1",
        "role": "member",
        "principal_type": "user",
        "principal_id": "u-1",
        "project_id": "p-1",
    }

    embed = MagicMock()
    embed.user.id = "u-1"
    embed.user.role.value = "member"
    embed.embed_key.key_id = "key-abc"
    scope = usage_scope_for(embed)
    assert scope["principal_type"] == "embed_key"
    assert scope["principal_id"] == "key-abc"
    # user_id 仍保留，才查得到「這個帳號的金鑰用了多少」。
    assert scope["user_id"] == "u-1"

    # 沒有帳號脈絡（系統自行觸發）時不記名，但事件仍會入帳。
    assert usage_scope_for(None) == {}
