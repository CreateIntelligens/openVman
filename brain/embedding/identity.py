"""Canonical embedding identity and specification definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EmbeddingSpec:
    """Canonical specification defining an embedding vector representation."""

    identity: str
    provider: str
    model: str
    dimensions: int
    dtype: str = "float32"
    normalized: bool = True
    normalization: str = "l2"
    input_semantics: str = "document"
    model_revision: str = "default"
    service_revision: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_canonical_identity(
    provider: str,
    model: str,
    dimensions: int,
    dtype: str = "float32",
    normalization: str = "l2",
    input_semantics: str = "document",
    model_revision: str = "default",
) -> str:
    """Generate deterministic canonical identity string.

    Format: <provider>:<model>:<dimensions>:<dtype>:<normalization>:<input_semantics>:<model_revision>
    """
    clean_provider = provider.strip().lower()
    clean_model = model.strip()
    clean_dtype = dtype.strip().lower()
    clean_norm = normalization.strip().lower()
    clean_semantics = input_semantics.strip().lower()
    clean_model_rev = model_revision.strip()
    return f"{clean_provider}:{clean_model}:{dimensions}:{clean_dtype}:{clean_norm}:{clean_semantics}:{clean_model_rev}"


def parse_canonical_identity(identity: str, service_revision: str = "1.0.0") -> EmbeddingSpec:
    """Parse canonical identity string into an EmbeddingSpec."""
    parts = identity.strip().split(":")
    if len(parts) == 7:
        provider, model, dims_str, dtype, norm, semantics, model_rev = parts
    elif len(parts) == 6:
        # Legacy 6-part format: provider:model:dims:dtype:norm:revision
        provider, model, dims_str, dtype, norm, model_rev = parts
        semantics = "document"
    else:
        raise ValueError(
            f"Invalid canonical identity format: {identity!r}. "
            f"Expected 'provider:model:dimensions:dtype:normalization:input_semantics:model_revision'"
        )

    try:
        dimensions = int(dims_str)
    except ValueError:
        raise ValueError(f"Invalid dimensions in identity: {dims_str!r}")

    normalized = norm.lower() not in {"none", "false", "unnormalized"}
    return EmbeddingSpec(
        identity=identity,
        provider=provider,
        model=model,
        dimensions=dimensions,
        dtype=dtype,
        normalized=normalized,
        normalization=norm,
        input_semantics=semantics,
        model_revision=model_rev,
        service_revision=service_revision,
    )
