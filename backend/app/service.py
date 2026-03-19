"""TTS router service — bounded fallback chain across providers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from app.config import TTSRouterConfig, get_tts_config
from app.observability import (
    record_chain_exhausted,
    record_fallback_hop,
    record_provider_request,
    record_route_attempt,
)
from app.providers.aws_adapter import AWSPollyAdapter
from app.providers.base import NormalizedTTSResult, ProviderAdapter, SynthesizeRequest
from app.providers.edge_tts_adapter import EdgeTTSAdapter
from app.providers.error_mapping import (
    classify_aws_error,
    classify_edge_tts_error,
    classify_gcp_error,
    classify_index_error,
)
from app.providers.gcp_adapter import GCPTTSAdapter
from app.providers.index_tts_adapter import IndexTTSAdapter


@dataclass(frozen=True, slots=True)
class RouteTarget:
    """A single hop in the TTS fallback chain."""

    target: str  # e.g. "index-tts", "aws-polly", "gcp-tts", "edge-tts"
    adapter: ProviderAdapter
    error_classifier: Callable[[Exception], str]


class TTSRouterService:
    """Execute a bounded fallback chain: Index TTS -> GCP -> AWS -> Edge-TTS."""

    def __init__(self, config: TTSRouterConfig | None = None) -> None:
        self._config = config or get_tts_config()
        self._index = IndexTTSAdapter(self._config)
        self._aws = AWSPollyAdapter(self._config)
        self._gcp = GCPTTSAdapter(self._config)
        self._edge = EdgeTTSAdapter(self._config)

    def build_chain(self) -> list[RouteTarget]:
        """Build the ordered fallback chain based on config."""
        return [
            RouteTarget(
                target=target_id,
                adapter=adapter,
                error_classifier=classifier,
            )
            for target_id, adapter, classifier in self._provider_routes()
            if adapter.enabled
        ]

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """Run the fallback chain and return the first successful result.

        Raises RuntimeError if all hops fail.
        """
        chain = self.build_chain()
        if not chain:
            raise RuntimeError("TTS fallback chain 為空：無可用的 provider")

        errors: list[str] = []
        last_reason = ""

        for i, target in enumerate(chain):
            t0 = monotonic()
            try:
                result = target.adapter.synthesize(request)
                latency_ms = (monotonic() - t0) * 1000
                record_route_attempt(
                    target=target.target, result="success", latency_ms=latency_ms,
                )
                record_provider_request(provider=target.target, result="success")
                return result
            except Exception as exc:
                latency_ms = (monotonic() - t0) * 1000
                last_reason = target.error_classifier(exc)
                record_route_attempt(
                    target=target.target,
                    result="failure",
                    latency_ms=latency_ms,
                    reason=last_reason,
                )
                record_provider_request(provider=target.target, result="failure")
                errors.append(f"{target.target}: {type(exc).__name__}: {exc}")

                # Record fallback hop to next target (if any)
                if i + 1 < len(chain):
                    record_fallback_hop(
                        from_target=target.target,
                        to_target=chain[i + 1].target,
                        reason=last_reason,
                    )

        record_chain_exhausted(final_reason=last_reason, hops=len(chain))
        raise RuntimeError(
            "所有 TTS fallback chain hops 皆失敗: " + " | ".join(errors)
        )

    def _provider_routes(
        self,
    ) -> tuple[tuple[str, ProviderAdapter, Callable[[Exception], str]], ...]:
        return (
            ("index-tts", self._index, classify_index_error),
            ("gcp-tts", self._gcp, classify_gcp_error),
            ("aws-polly", self._aws, classify_aws_error),
            ("edge-tts", self._edge, classify_edge_tts_error),
        )
