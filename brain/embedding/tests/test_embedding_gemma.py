"""EmbeddingGemma 2 provider: prefixes, normalization, titles and identity."""

from __future__ import annotations

import asyncio
import math
import sys
import types

import numpy as np
import pytest

try:
    from brain.embedding.local_providers import GemmaLocalProvider
    from brain.embedding.registry import ProviderRegistry
except ModuleNotFoundError:
    from local_providers import GemmaLocalProvider
    from registry import ProviderRegistry


class _FakeSentenceTransformer:
    calls: list[list[str]] = []

    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.max_seq_length = 0

    def encode(self, inputs, **_kwargs):
        type(self).calls.append(list(inputs))
        return np.array([[3.0, 4.0] + [1.0] * 766 for _ in inputs], dtype=np.float32)


@pytest.fixture
def fake_st(monkeypatch):
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = _FakeSentenceTransformer
    torch_module = types.ModuleType("torch")
    torch_module.bfloat16 = "bf16"
    torch_module.float32 = "fp32"
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setitem(sys.modules, "torch", torch_module)
    _FakeSentenceTransformer.calls = []
    return _FakeSentenceTransformer


@pytest.mark.asyncio
async def test_queries_and_documents_get_their_own_prefixes(fake_st):
    provider = GemmaLocalProvider(device="cpu")
    await provider.encode(["沉水泵多深"], input_type="query")
    await provider.encode(["內文"], input_type="document", titles=["EVAK_CATALOG"])
    await provider.encode(["沒有標題"], input_type="document")
    await provider.encode(["這種針劑"], input_type="search_query")
    assert fake_st.calls == [
        ["task: question answering | query: 沉水泵多深"],
        ["title: EVAK_CATALOG | text: 內文"],
        ["title: none | text: 沒有標題"],
        ["task: search result | query: 這種針劑"],
    ]
    assert provider.spec("search_query").identity.endswith(":search_query:default")


@pytest.mark.asyncio
async def test_vectors_are_768_dimensional_and_normalized(fake_st):
    provider = GemmaLocalProvider(device="cpu")
    [vector] = await provider.encode(["x"], input_type="query")
    assert len(vector) == 768
    assert math.isclose(sum(v * v for v in vector), 1.0, rel_tol=1e-6)
    assert provider.spec("query").identity == "gemma:google/embeddinggemma-2:768:float32:l2:query:default"


@pytest.mark.asyncio
async def test_registry_passes_titles_only_to_providers_that_take_them(fake_st):
    seen: dict[str, object] = {}

    class TitleBlind:
        is_configured = True

        def spec(self, input_semantics="document"):
            return GemmaLocalProvider(device="cpu").spec(input_semantics).__class__(
                identity="other:m:2:float32:l2:document:x", provider="other", model="m", dimensions=2,
            )

        async def encode(self, texts, *, input_type="document"):
            seen["blind"] = True
            return [[1.0, 0.0] for _ in texts]

    registry = ProviderRegistry(fallback_order=["blind", "gemma"])
    registry.register("blind", TitleBlind())
    registry.register("gemma", GemmaLocalProvider(device="cpu"))

    await registry.resolve_and_encode(["a"], titles=["t"])
    assert seen == {"blind": True}

    gemma_identity = GemmaLocalProvider(device="cpu").spec("document").identity
    await registry.resolve_and_encode(["a"], titles=["t"], requested_identity=gemma_identity)
    assert fake_st.calls[-1] == ["title: t | text: a"]


@pytest.mark.asyncio
async def test_caller_order_of_acceptable_identities_wins_over_fallback_order(fake_st):
    registry = ProviderRegistry(fallback_order=["other", "gemma"])

    class Other:
        is_configured = True

        def spec(self, input_semantics="document"):
            return GemmaLocalProvider(device="cpu").spec(input_semantics).__class__(
                identity=f"other:m:2:float32:l2:{input_semantics}:r", provider="other",
                model="m", dimensions=2,
            )

        async def encode(self, texts, *, input_type="document"):
            return [[1.0, 0.0] for _ in texts]

    registry.register("other", Other())
    registry.register("gemma", GemmaLocalProvider(device="cpu"))
    gemma_query = GemmaLocalProvider(device="cpu").spec("query").identity
    other_query = Other().spec("query").identity

    _, spec, _ = await registry.resolve_and_encode(
        ["q"], input_type="query", acceptable_identities=[gemma_query, other_query],
    )
    assert spec.provider == "gemma"
    _, spec, _ = await registry.resolve_and_encode(
        ["q"], input_type="query", acceptable_identities=[other_query, gemma_query],
    )
    assert spec.provider == "other"


class _IndexedModel:
    """Each vector encodes its input text's length, so split results can be checked."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, inputs, **_kwargs):
        self.calls.append(list(inputs))
        if any("BAD" in text for text in inputs):
            raise RuntimeError("bad input")
        return np.array([[float(len(text)), 1.0] + [0.0] * 766 for text in inputs], dtype=np.float32)


async def _loaded_provider(fake_st) -> tuple[GemmaLocalProvider, _IndexedModel]:
    provider = GemmaLocalProvider(device="cpu")
    await provider.encode(["warm"], input_type="query")
    model = _IndexedModel()
    provider._model = model
    return provider, model


def _length_of(vector: list[float]) -> float:
    # 向量是 [len, 1, 0...] 正規化後的結果，比例還原長度。
    return round(vector[0] / vector[1])


@pytest.mark.asyncio
async def test_queued_requests_share_one_model_call(fake_st):
    provider, model = await _loaded_provider(fake_st)

    results = await asyncio.gather(
        provider.encode(["a"], input_type="document"),
        provider.encode(["bb", "ccc"], input_type="document"),
        provider.encode(["dddd"], input_type="document"),
    )

    assert len(model.calls) == 1
    prefix = len("title: none | text: ")
    assert [[_length_of(v) - prefix for v in vectors] for vectors in results] == [[1], [2, 3], [4]]
    await provider.shutdown()


@pytest.mark.asyncio
async def test_a_failing_request_does_not_fail_the_rest_of_its_batch(fake_st):
    provider, model = await _loaded_provider(fake_st)

    results = await asyncio.gather(
        provider.encode(["ok one"], input_type="query"),
        provider.encode(["BAD"], input_type="query"),
        provider.encode(["ok two"], input_type="query"),
        return_exceptions=True,
    )

    assert isinstance(results[1], RuntimeError)
    assert not isinstance(results[0], Exception) and not isinstance(results[2], Exception)
    assert len(model.calls) == 4  # 合批一次失敗，再逐一重算三次
    await provider.shutdown()


@pytest.mark.asyncio
async def test_batches_stop_at_the_size_limit(fake_st, monkeypatch):
    import local_providers

    monkeypatch.setattr(local_providers, "_MERGE_MAX_TEXTS", 3)
    provider, model = await _loaded_provider(fake_st)

    await asyncio.gather(*(provider.encode([str(i)], input_type="query") for i in range(5)))

    assert [len(call) for call in model.calls] == [3, 2]
    await provider.shutdown()


@pytest.mark.asyncio
async def test_queries_run_before_queued_documents(fake_st):
    provider, model = await _loaded_provider(fake_st)

    await asyncio.gather(
        provider.encode(["doc"], input_type="document"),
        provider.encode(["q1"], input_type="search_query"),
        provider.encode(["q2"], input_type="query"),
    )

    assert model.calls[0] == ["task: search result | query: q1", "task: question answering | query: q2"]
    assert model.calls[1] == ["title: none | text: doc"]
    await provider.shutdown()


@pytest.mark.asyncio
async def test_documents_are_not_starved_by_a_stream_of_queries(fake_st, monkeypatch):
    import local_providers

    monkeypatch.setattr(local_providers, "_MERGE_MAX_TEXTS", 1)
    provider, model = await _loaded_provider(fake_st)

    await asyncio.gather(
        provider.encode(["doc"], input_type="document"),
        *(provider.encode([f"q{i}"], input_type="query") for i in range(8)),
    )

    order = [call[0] for call in model.calls]
    assert order.index("title: none | text: doc") == local_providers._QUERY_BATCHES_BEFORE_DOCUMENTS
    await provider.shutdown()
