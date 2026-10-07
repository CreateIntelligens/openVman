"""Unit tests for ProviderRegistry fallback, cooldowns, identity constraints and attempts."""

from __future__ import annotations

import pytest

try:
    from brain.embedding.identity import EmbeddingSpec, make_canonical_identity
    from brain.embedding.registry import ProviderRegistry
except ModuleNotFoundError:
    from identity import EmbeddingSpec, make_canonical_identity
    from registry import ProviderRegistry


def _spec(provider: str, dimensions: int, input_semantics: str = "query") -> EmbeddingSpec:
    model = f"fake/{provider}"
    return EmbeddingSpec(
        identity=make_canonical_identity(provider, model, dimensions, input_semantics=input_semantics),
        provider=provider,
        model=model,
        dimensions=dimensions,
        input_semantics=input_semantics,
    )


class FakeProvider:
    def __init__(self, spec: EmbeddingSpec, *, fail: bool = False) -> None:
        self._spec = spec
        self.fail = fail
        self.encode_calls = 0

    @property
    def is_configured(self) -> bool:
        return True

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        return self._spec

    async def is_ready(self) -> bool:
        return not self.fail

    async def warmup(self) -> None:
        if self.fail:
            raise RuntimeError("Service unavailable")

    async def encode(self, texts: list[str], *, input_type: str = "document") -> list[list[float]]:
        self.encode_calls += 1
        if self.fail:
            raise RuntimeError(f"Provider {self._spec.provider} connection failed")
        return [[0.5] * self._spec.dimensions for _ in texts]

    async def shutdown(self) -> None:
        pass


def _registry(primary_fail: bool = True) -> tuple[ProviderRegistry, FakeProvider, FakeProvider]:
    reg = ProviderRegistry(cooldown_seconds=10.0, fallback_order=["primary", "secondary"])
    primary = FakeProvider(_spec("primary", 4), fail=primary_fail)
    secondary = FakeProvider(_spec("secondary", 3))
    reg.register("primary", primary)
    reg.register("secondary", secondary)
    return reg, primary, secondary


def test_default_fallback_order_is_gemma_only():
    assert ProviderRegistry().fallback_order == ["gemma"]


@pytest.mark.asyncio
async def test_registry_fallback_to_second_provider_reports_attempts():
    reg, _, _ = _registry()

    vectors, spec, attempts = await reg.resolve_and_encode(["測試文字"], input_type="query")

    assert len(vectors) == 1
    assert len(vectors[0]) == 3
    assert spec.provider == "secondary"
    assert [(a["provider"], a["status"]) for a in attempts] == [
        ("primary", "error"),
        ("secondary", "selected"),
    ]
    assert attempts[0]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_failed_provider_is_skipped_while_in_cooldown():
    reg, primary, _ = _registry()

    await reg.resolve_and_encode(["a"], input_type="query")
    _, spec, attempts = await reg.resolve_and_encode(["b"], input_type="query")

    assert spec.provider == "secondary"
    assert attempts[0]["provider"] == "primary"
    assert attempts[0]["status"] == "cooldown"
    assert primary.encode_calls == 1


@pytest.mark.asyncio
async def test_registry_respects_acceptable_identities():
    reg, primary, _ = _registry()

    with pytest.raises(RuntimeError) as exc_info:
        await reg.resolve_and_encode(
            ["測試文字"],
            input_type="query",
            acceptable_identities=[primary.spec().identity],
        )
    assert "No acceptable embedding provider succeeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_acceptable_identities_order_wins_over_fallback_order():
    reg, primary, secondary = _registry(primary_fail=False)

    _, spec, attempts = await reg.resolve_and_encode(
        ["q"],
        input_type="query",
        acceptable_identities=[secondary.spec().identity, primary.spec().identity],
    )

    assert spec.provider == "secondary"
    assert [a["provider"] for a in attempts] == ["secondary"]


@pytest.mark.asyncio
async def test_requested_identity_pins_the_exact_provider():
    reg, _, secondary = _registry(primary_fail=False)

    _, spec, attempts = await reg.resolve_and_encode(
        ["q"], input_type="query", requested_identity=secondary.spec().identity,
    )

    assert spec.identity == secondary.spec().identity
    assert [a["provider"] for a in attempts] == ["secondary"]


@pytest.mark.asyncio
async def test_unmatched_identity_fails_before_encoding():
    reg, primary, secondary = _registry(primary_fail=False)

    with pytest.raises(RuntimeError, match="No configured embedding provider matched"):
        await reg.resolve_and_encode(
            ["q"], input_type="query", requested_identity="unknown:m:1:float32:l2:query:r",
        )
    assert primary.encode_calls == secondary.encode_calls == 0


@pytest.mark.asyncio
async def test_dimension_mismatch_counts_as_provider_error():
    reg = ProviderRegistry(fallback_order=["liar"])

    class Liar(FakeProvider):
        async def encode(self, texts, *, input_type="document"):
            return [[0.1] * 2 for _ in texts]

    reg.register("liar", Liar(_spec("liar", 4)))

    with pytest.raises(RuntimeError):
        await reg.resolve_and_encode(["q"], input_type="query")
