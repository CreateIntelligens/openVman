"""TTS router service — bounded fallback chain across providers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
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
    classify_vibevoice_error,
)
from app.providers.gcp_adapter import GCPTTSAdapter
from app.providers.vibevoice_adapter import VibeVoiceAdapter


@dataclass(frozen=True, slots=True)
class RouteTarget:
    """A single hop in the TTS fallback chain."""

    target: str  # e.g. "vibevoice", "aws-polly", "gcp-tts", "edge-tts"
    adapter: ProviderAdapter
    error_classifier: Callable[[Exception], str]


@dataclass(frozen=True, slots=True)
class SynthesisOutput:
    """Wraps a TTS result with optional fallback metadata."""

    result: NormalizedTTSResult
    fallback: bool = False
    fallback_reason: str = ""


class TTSRouterService:
    """Execute a bounded fallback chain: VibeVoice -> GCP -> AWS -> Edge-TTS."""

    def __init__(self, config: TTSRouterConfig | None = None) -> None:
        self._config = config or get_tts_config()
        self._vibevoice = VibeVoiceAdapter(self._config)
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

    def synthesize(
        self, request: SynthesizeRequest, *, provider: str = "",
    ) -> SynthesisOutput:
        """Run the fallback chain and return the first successful result.

        When *provider* is given (not "" or "auto"), only that provider is
        attempted first.  On failure it falls back to Edge-TTS and marks the
        output with ``fallback=True``.

        Raises RuntimeError if all attempts fail.
        """
        chain = self.build_chain()
        if not chain:
            raise RuntimeError("TTS fallback chain 為空：無可用的 provider")

        if provider and provider != "auto":
            return self._synthesize_targeted(request, provider, chain)

        return self._synthesize_chain(request, chain)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _try_synthesize(
        target: RouteTarget, request: SynthesizeRequest,
    ) -> tuple[NormalizedTTSResult | None, str, str]:
        """Try one provider and record metrics.

        Returns ``(result, classified_reason, error_desc)`` — *result*
        is ``None`` on failure; *classified_reason* is the short
        classifier tag (e.g. ``"timeout"``); *error_desc* is a
        human-readable summary.
        """
        t0 = monotonic()
        try:
            result = target.adapter.synthesize(request)
            latency_ms = (monotonic() - t0) * 1000
            record_route_attempt(
                target=target.target, result="success", latency_ms=latency_ms,
            )
            record_provider_request(provider=target.target, result="success")
            return result, "", ""
        except Exception as exc:
            latency_ms = (monotonic() - t0) * 1000
            reason = target.error_classifier(exc)
            record_route_attempt(
                target=target.target,
                result="failure",
                latency_ms=latency_ms,
                reason=reason,
            )
            record_provider_request(provider=target.target, result="failure")
            desc = f"{target.target}: {type(exc).__name__}: {exc}"
            return None, reason, desc

    def _synthesize_chain(
        self, request: SynthesizeRequest, chain: list[RouteTarget],
    ) -> SynthesisOutput:
        """Full fallback chain (existing behaviour)."""
        errors: list[str] = []
        last_reason = ""

        for i, target in enumerate(chain):
            result, reason, error_desc = self._try_synthesize(target, request)
            if result is not None:
                return SynthesisOutput(result=result)

            last_reason = reason
            errors.append(error_desc)

            if i + 1 < len(chain):
                record_fallback_hop(
                    from_target=target.target,
                    to_target=chain[i + 1].target,
                    reason=reason,
                )

        record_chain_exhausted(final_reason=last_reason, hops=len(chain))
        raise RuntimeError(
            "所有 TTS fallback chain hops 皆失敗: " + " | ".join(errors)
        )

    def _synthesize_targeted(
        self,
        request: SynthesizeRequest,
        provider: str,
        chain: list[RouteTarget],
    ) -> SynthesisOutput:
        """Try a specific provider, fall back to Edge-TTS on failure."""
        target = next(
            (t for t in chain if t.adapter.provider_name == provider), None,
        )
        if target is None:
            raise RuntimeError(f"未知的 TTS provider: {provider}")

        result, reason, primary_error = self._try_synthesize(target, request)
        if result is not None:
            return SynthesisOutput(result=result)

        # Fallback to Edge-TTS
        edge = next(
            (t for t in chain if t.adapter.provider_name == "edge-tts"), None,
        )
        if edge is None or edge.adapter.provider_name == provider:
            raise RuntimeError(f"TTS provider 失敗且無法 fallback: {primary_error}")

        record_fallback_hop(
            from_target=target.target, to_target=edge.target, reason=reason,
        )

        edge_request = replace(request, voice_hint="")
        edge_result, _, edge_error = self._try_synthesize(edge, edge_request)
        if edge_result is not None:
            return SynthesisOutput(
                result=edge_result,
                fallback=True,
                fallback_reason=primary_error,
            )

        raise RuntimeError(
            f"TTS provider 及 Edge-TTS fallback 皆失敗: "
            f"{primary_error} | {edge_error}"
        )

    def _provider_routes(
        self,
    ) -> tuple[tuple[str, ProviderAdapter, Callable[[Exception], str]], ...]:
        return (
            ("vibevoice", self._vibevoice, classify_vibevoice_error),
            ("gcp-tts", self._gcp, classify_gcp_error),
            ("aws-polly", self._aws, classify_aws_error),
            ("edge-tts", self._edge, classify_edge_tts_error),
        )
