"""TTS router service — bounded fallback chain across nodes and providers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from app.config import TTSRouterConfig, get_tts_config
from app.node_health import NodeHealthManager, NodeHealthPolicy, NodeState
from app.observability import (
    record_chain_exhausted,
    record_fallback_hop,
    record_node_bypassed,
    record_node_failover,
    record_node_selected,
    record_provider_request,
    record_route_attempt,
)
from app.providers.aws_adapter import AWSPollyAdapter
from app.providers.base import NormalizedTTSResult, ProviderAdapter, SynthesizeRequest
from app.providers.error_mapping import (
    classify_aws_error,
    classify_gcp_error,
    classify_node_error,
)
from app.providers.gcp_adapter import GCPTTSAdapter
from app.providers.node_adapter import NodeAdapter


@dataclass(frozen=True, slots=True)
class RouteTarget:
    """A single hop in the TTS fallback chain."""

    kind: str  # "node" | "provider"
    target: str  # e.g. "tts-primary", "aws-polly", "gcp-tts"
    adapter: ProviderAdapter | NodeAdapter
    error_classifier: Callable[[Exception], str]


class TTSRouterService:
    """Execute a bounded fallback chain: nodes -> AWS -> GCP."""

    def __init__(self, config: TTSRouterConfig | None = None) -> None:
        self._config = config or get_tts_config()
        self._aws = AWSPollyAdapter(self._config)
        self._gcp = GCPTTSAdapter(self._config)

        # Build node health manager from config
        policy = NodeHealthPolicy(
            failure_threshold=self._config.node_failure_threshold,
            cooldown_seconds=self._config.node_cooldown_seconds,
            score_penalty=self._config.node_score_penalty,
        )
        nodes: list[NodeState] = []
        if self._config.tts_primary_node:
            nodes.append(NodeState(
                node_id="tts-primary",
                role="primary",
                base_url=self._config.tts_primary_node,
                priority=0,
            ))
        if self._config.tts_secondary_node:
            nodes.append(NodeState(
                node_id="tts-secondary",
                role="secondary",
                base_url=self._config.tts_secondary_node,
                priority=1,
            ))
        self._health = NodeHealthManager(nodes, policy)
        self._node_adapters: dict[str, NodeAdapter] = {
            n.node_id: NodeAdapter(
                n.node_id,
                n.base_url,
                timeout_ms=self._config.node_timeout_ms,
            )
            for n in nodes
        }

    @property
    def health_manager(self) -> NodeHealthManager:
        return self._health

    def build_chain(self) -> list[RouteTarget]:
        """Build the ordered fallback chain based on config and health state."""
        chain: list[RouteTarget] = []

        # Self-hosted nodes — only include healthy ones
        healthy_nodes = self._health.get_healthy_nodes()
        healthy_ids = {n.node_id for n in healthy_nodes}

        # Log bypassed nodes
        for node in self._health.get_all_states():
            if node.node_id not in healthy_ids:
                reason = "cooldown" if node.healthy else "unhealthy"
                record_node_bypassed(node_id=node.node_id, reason=reason)

        for node in healthy_nodes:
            adapter = self._node_adapters.get(node.node_id)
            if adapter is not None:
                record_node_selected(
                    node_id=node.node_id,
                    role=node.role,
                    score=node.score,
                )
                chain.append(
                    RouteTarget(
                        kind="node",
                        target=node.node_id,
                        adapter=adapter,
                        error_classifier=classify_node_error,
                    )
                )

        # AWS provider
        if self._aws.enabled:
            chain.append(
                RouteTarget(
                    kind="provider",
                    target="aws-polly",
                    adapter=self._aws,
                    error_classifier=classify_aws_error,
                )
            )

        # GCP provider
        if self._gcp.enabled:
            chain.append(
                RouteTarget(
                    kind="provider",
                    target="gcp-tts",
                    adapter=self._gcp,
                    error_classifier=classify_gcp_error,
                )
            )

        return chain

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
                    kind=target.kind,
                    target=target.target,
                    result="success",
                    latency_ms=latency_ms,
                )
                record_provider_request(provider=target.target, result="success")

                if target.kind == "node":
                    self._health.record_success(target.target)

                return result
            except Exception as exc:
                latency_ms = (monotonic() - t0) * 1000
                reason = target.error_classifier(exc)
                last_reason = reason
                record_route_attempt(
                    kind=target.kind,
                    target=target.target,
                    result="failure",
                    latency_ms=latency_ms,
                    reason=reason,
                )
                record_provider_request(provider=target.target, result="failure")
                errors.append(f"{target.target}: {type(exc).__name__}: {exc}")

                if target.kind == "node":
                    self._health.record_failure(target.target)

                # Record fallback hop to next target
                next_t = chain[i + 1] if i + 1 < len(chain) else None
                if next_t is not None:
                    if target.kind == "node":
                        record_node_failover(
                            from_node=target.target,
                            to_target=next_t.target,
                            reason=reason,
                        )
                    record_fallback_hop(
                        from_kind=target.kind,
                        from_target=target.target,
                        to_kind=next_t.kind,
                        to_target=next_t.target,
                        reason=reason,
                    )

        record_chain_exhausted(final_reason=last_reason, hops=len(chain))
        raise RuntimeError(
            "所有 TTS fallback chain hops 皆失敗: " + " | ".join(errors)
        )
