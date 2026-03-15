"""Provider adapter contract and shared data types for TTS routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SynthesizeRequest:
    """Input for any TTS provider adapter."""

    text: str
    locale: str = "zh-TW"
    sample_rate: int = 24000
    voice_hint: str = ""


@dataclass(frozen=True, slots=True)
class NormalizedTTSResult:
    """Unified result shape returned by every provider adapter."""

    audio_bytes: bytes
    content_type: str
    sample_rate: int
    provider: str
    route_kind: str  # "node" | "provider"
    route_target: str
    latency_ms: float
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    """Contract that every TTS cloud provider adapter must satisfy."""

    @property
    def provider_name(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult: ...
