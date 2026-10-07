"""EmbeddingGemma 2 provider: prefixes, normalization, titles and identity."""

from __future__ import annotations

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
    assert fake_st.calls == [
        ["task: question answering | query: 沉水泵多深"],
        ["title: EVAK_CATALOG | text: 內文"],
        ["title: none | text: 沒有標題"],
    ]


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
    registry = ProviderRegistry(fallback_order=["bge", "gemma"])

    class Bge:
        is_configured = True

        def spec(self, input_semantics="document"):
            return GemmaLocalProvider(device="cpu").spec(input_semantics).__class__(
                identity=f"bge:BAAI/bge-m3:1024:float32:l2:{input_semantics}:r", provider="bge",
                model="BAAI/bge-m3", dimensions=1024,
            )

        async def encode(self, texts, *, input_type="document"):
            return [[1.0] + [0.0] * 1023 for _ in texts]

    registry.register("bge", Bge())
    registry.register("gemma", GemmaLocalProvider(device="cpu"))
    gemma_query = GemmaLocalProvider(device="cpu").spec("query").identity
    bge_query = Bge().spec("query").identity

    _, spec, _ = await registry.resolve_and_encode(
        ["q"], input_type="query", acceptable_identities=[gemma_query, bge_query],
    )
    assert spec.provider == "gemma"
    _, spec, _ = await registry.resolve_and_encode(
        ["q"], input_type="query", acceptable_identities=[bge_query, gemma_query],
    )
    assert spec.provider == "bge"
