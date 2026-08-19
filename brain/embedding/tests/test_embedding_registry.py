"""Unit tests for ProviderRegistry, gateway fallback, cooldowns, and attempt reporting."""

from __future__ import annotations

import pytest

try:
    from brain.embedding.identity import EmbeddingSpec, make_canonical_identity
    from brain.embedding.registry import ProviderRegistry
except ModuleNotFoundError:
    from identity import EmbeddingSpec, make_canonical_identity
    from registry import ProviderRegistry


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
