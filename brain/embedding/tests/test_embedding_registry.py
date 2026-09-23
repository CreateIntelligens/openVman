"""Unit tests for ProviderRegistry, gateway fallback, cooldowns, and attempt reporting."""

from __future__ import annotations

import sys
import types

import httpx
import pytest

try:
    from brain.embedding.identity import EmbeddingSpec, make_canonical_identity
    from brain.embedding.registry import (
        BgeLocalProvider,
        GeminiApiProvider,
        OpenAiApiProvider,
        ProviderRegistry,
        VoyageApiProvider,
        _parse_retry_after,
        _post_with_retry,
    )
except ModuleNotFoundError:
    from identity import EmbeddingSpec, make_canonical_identity
    from registry import (
        BgeLocalProvider,
        GeminiApiProvider,
        OpenAiApiProvider,
        ProviderRegistry,
        VoyageApiProvider,
        _parse_retry_after,
        _post_with_retry,
    )


@pytest.mark.asyncio
async def test_bge_resolves_the_pinned_huggingface_snapshot(monkeypatch):
    observed: dict[str, str] = {}
    flag_module = types.ModuleType("FlagEmbedding")

    class FakeModel:
        def __init__(self, model_source, **_kwargs):
            observed["model_source"] = model_source

    flag_module.BGEM3FlagModel = FakeModel
    hub_module = types.ModuleType("huggingface_hub")

    def fake_snapshot_download(*, repo_id, revision):
        observed["repo_id"] = repo_id
        observed["revision"] = revision
        return "/cache/exact-snapshot"

    hub_module.snapshot_download = fake_snapshot_download
    monkeypatch.setitem(sys.modules, "FlagEmbedding", flag_module)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub_module)

    provider = BgeLocalProvider(
        model_name="BAAI/bge-m3",
        model_revision="fixed-revision",
        device="cpu",
        use_fp16=False,
    )
    await provider._get_or_load_model()

    assert observed == {
        "repo_id": "BAAI/bge-m3",
        "revision": "fixed-revision",
        "model_source": "/cache/exact-snapshot",
    }


class MockFailingProvider:
    def __init__(self, spec: EmbeddingSpec) -> None:
        self._spec = spec

    @property
    def is_configured(self) -> bool:
        return True

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        return self._spec

    async def is_ready(self) -> bool:
        return False

    async def warmup(self) -> None:
        raise RuntimeError("Service unavailable")

    async def encode(self, texts: list[str], *, input_type: str = "document") -> list[list[float]]:
        raise RuntimeError(f"Provider {self._spec.provider} connection failed")

    async def shutdown(self) -> None:
        pass


class MockSuccessProvider:
    def __init__(self, spec: EmbeddingSpec) -> None:
        self._spec = spec

    @property
    def is_configured(self) -> bool:
        return True

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        return self._spec

    async def is_ready(self) -> bool:
        return True

    async def warmup(self) -> None:
        pass

    async def encode(self, texts: list[str], *, input_type: str = "document") -> list[list[float]]:
        return [[0.5] * self._spec.dimensions for _ in texts]

    async def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_registry_fallback_to_second_provider():
    reg = ProviderRegistry(cooldown_seconds=10.0)

    bge_spec = EmbeddingSpec(
        identity=make_canonical_identity("bge", "BAAI/bge-m3", 1024, input_semantics="query"),
        provider="bge",
        model="BAAI/bge-m3",
        dimensions=1024,
    )
    gemini_spec = EmbeddingSpec(
        identity=make_canonical_identity("gemini", "text-embedding-004", 768, input_semantics="query"),
        provider="gemini",
        model="text-embedding-004",
        dimensions=768,
    )

    reg.register("bge", MockFailingProvider(bge_spec))
    reg.register("gemini", MockSuccessProvider(gemini_spec))

    vectors, spec, attempts = await reg.resolve_and_encode(["測試文字"], input_type="query")
    assert len(vectors) == 1
    assert len(vectors[0]) == 768
    assert spec.provider == "gemini"
    assert len(attempts) == 2
    assert attempts[0]["provider"] == "bge"
    assert attempts[0]["status"] == "error"
    assert attempts[1]["provider"] == "gemini"
    assert attempts[1]["status"] == "selected"


@pytest.mark.asyncio
async def test_registry_respects_acceptable_identities():
    reg = ProviderRegistry(cooldown_seconds=10.0)

    bge_spec = EmbeddingSpec(
        identity=make_canonical_identity("bge", "BAAI/bge-m3", 1024, input_semantics="query"),
        provider="bge",
        model="BAAI/bge-m3",
        dimensions=1024,
    )
    openai_spec = EmbeddingSpec(
        identity=make_canonical_identity("openai", "text-embedding-3-small", 1536, input_semantics="query"),
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1536,
    )

    reg.register("bge", MockFailingProvider(bge_spec))
    reg.register("openai", MockSuccessProvider(openai_spec))

    with pytest.raises(RuntimeError) as exc_info:
        await reg.resolve_and_encode(
            ["測試文字"],
            input_type="query",
            acceptable_identities=[bge_spec.identity],
        )
    assert "No acceptable embedding provider succeeded" in str(exc_info.value)


def test_parse_retry_after():
    assert _parse_retry_after(None, 10.0) is None
    assert _parse_retry_after("", 10.0) is None
    assert _parse_retry_after("invalid", 10.0) is None
    assert _parse_retry_after("3", 10.0) == 3.0
    assert _parse_retry_after("2.5", 10.0) == 2.5
    assert _parse_retry_after("15", 8.0) == 8.0  # capped at max_delay
    assert _parse_retry_after("-1", 10.0) is None


@pytest.mark.asyncio
async def test_post_with_retry_recovers_from_429():
    calls = 0

    class FakeClient:
        async def post(self, url, json=None, headers=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                req = httpx.Request("POST", url)
                return httpx.Response(429, headers={"retry-after": "0.01"}, request=req)
            req = httpx.Request("POST", url)
            return httpx.Response(200, json={"ok": True}, request=req)

    resp = await _post_with_retry(
        FakeClient(),
        "http://test-api/embeddings",
        json={"input": "test"},
        headers={},
        max_retries=2,
        base_delay=0.01,
        max_delay=0.1,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_post_with_retry_stops_on_401():
    calls = 0

    class FakeClient:
        async def post(self, url, json=None, headers=None):
            nonlocal calls
            calls += 1
            req = httpx.Request("POST", url)
            return httpx.Response(401, json={"error": "unauthorized"}, request=req)

    with pytest.raises(httpx.HTTPStatusError):
        await _post_with_retry(
            FakeClient(),
            "http://test-api/embeddings",
            json={},
            headers={},
            max_retries=3,
            base_delay=0.01,
        )
    assert calls == 1  # 401 is not retryable, must fail immediately


@pytest.mark.asyncio
async def test_post_with_retry_exhausts_and_raises():
    calls = 0

    class FakeClient:
        async def post(self, url, json=None, headers=None):
            nonlocal calls
            calls += 1
            req = httpx.Request("POST", url)
            return httpx.Response(429, headers={"retry-after": "0.01"}, request=req)

    with pytest.raises(httpx.HTTPStatusError):
        await _post_with_retry(
            FakeClient(),
            "http://test-api/embeddings",
            json={},
            headers={},
            max_retries=2,
            base_delay=0.01,
            max_delay=0.05,
        )
    assert calls == 3  # initial attempt + 2 retries


@pytest.mark.asyncio
async def test_openai_provider_retries_429_and_succeeds():
    provider = OpenAiApiProvider(
        api_key="sk-test",
        max_retries=2,
        base_delay=0.01,
        max_delay=0.05,
    )
    calls = 0

    class FakeClient:
        async def post(self, url, json=None, headers=None):
            nonlocal calls
            calls += 1
            req = httpx.Request("POST", url)
            if calls == 1:
                return httpx.Response(429, headers={"retry-after": "0.01"}, request=req)
            return httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [0.1] * 1536}]},
                request=req,
            )

    provider._client = FakeClient()
    vectors = await provider.encode(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1536
    assert calls == 2
    assert provider._is_ready is True


@pytest.mark.asyncio
async def test_gemini_provider_retries_429_and_succeeds():
    provider = GeminiApiProvider(
        api_key="gemini-test",
        max_retries=2,
        base_delay=0.01,
        max_delay=0.05,
    )
    calls = 0

    class FakeClient:
        async def post(self, url, json=None, headers=None):
            nonlocal calls
            calls += 1
            req = httpx.Request("POST", url)
            if calls == 1:
                return httpx.Response(429, headers={"retry-after": "0.01"}, request=req)
            return httpx.Response(
                200,
                json={"embeddings": [{"values": [0.2] * 768}]},
                request=req,
            )

    provider._client = FakeClient()
    vectors = await provider.encode(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 768
    assert calls == 2
    assert provider._is_ready is True


class _FakeEncodeModel:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def encode_dense(self, texts, **_kwargs):
        if self.fail:
            raise RuntimeError("boom")
        return [[1.0, 0.0] for _ in texts]


def _fake_torch(monkeypatch, reserved_mb=(100, 100)) -> list[str]:
    calls: list[str] = []
    readings = iter(reserved_mb)
    torch_module = types.ModuleType("torch")
    torch_module.cuda = types.SimpleNamespace(
        empty_cache=lambda: calls.append("empty"),
        memory_reserved=lambda: next(readings) * 2**20,
        memory_allocated=lambda: 90 * 2**20,
    )
    monkeypatch.setitem(sys.modules, "torch", torch_module)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_bge_releases_cuda_cache_after_every_encode(monkeypatch, fail):
    calls = _fake_torch(monkeypatch)
    provider = BgeLocalProvider(device="cuda")
    provider._model = _FakeEncodeModel(fail=fail)
    provider._is_ready = True

    if fail:
        with pytest.raises(RuntimeError):
            await provider.encode(["a"])
    else:
        assert await provider.encode(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]
    assert calls == ["empty"]


@pytest.mark.asyncio
async def test_bge_on_cpu_does_not_touch_cuda(monkeypatch):
    calls = _fake_torch(monkeypatch)
    provider = BgeLocalProvider(device="cpu")
    provider._model = _FakeEncodeModel()
    provider._is_ready = True

    await provider.encode(["a"])
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved_mb, logged", [((3000, 2100), True), ((2110, 2100), False)])
async def test_bge_logs_only_meaningful_releases(monkeypatch, caplog, reserved_mb, logged):
    _fake_torch(monkeypatch, reserved_mb)
    provider = BgeLocalProvider(device="cuda")
    provider._model = _FakeEncodeModel()
    provider._is_ready = True
    caplog.set_level("INFO", logger="embedding_gateway.registry")

    await provider.encode(["a", "b", "c"])

    released = [r.getMessage() for r in caplog.records if "CUDA cache released" in r.getMessage()]
    if logged:
        assert released == ["CUDA cache released texts=3 reserved_mb=3000->2100 allocated_mb=90"]
    else:
        assert released == []
