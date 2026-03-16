"""HTTP adapter for self-hosted TTS worker nodes."""

from __future__ import annotations

from time import monotonic

import httpx

from app.providers.base import NormalizedTTSResult, SynthesizeRequest


class NodeAdapter:
    """Call a TTS worker node via HTTP and return a NormalizedTTSResult."""

    def __init__(self, node_id: str, base_url: str, timeout_ms: float = 10_000) -> None:
        self.node_id = node_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_ms / 1000

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /v1/synthesize on the worker node."""
        url = f"{self._base_url}/v1/synthesize"
        payload = {
            "text": request.text,
            "speaker_id": request.voice_hint,
            "locale": request.locale,
            "sample_rate": request.sample_rate,
        }

        t0 = monotonic()
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=payload)

        latency_ms = (monotonic() - t0) * 1000

        if resp.status_code >= 400:
            raise NodeHTTPError(
                status_code=resp.status_code,
                detail=resp.text[:500],
            )

        return NormalizedTTSResult(
            audio_bytes=resp.content,
            content_type=resp.headers.get("content-type", "audio/mpeg"),
            sample_rate=int(resp.headers.get("X-Sample-Rate", str(request.sample_rate))),
            provider="node",
            route_kind="node",
            route_target=self.node_id,
            latency_ms=round(latency_ms, 2),
            raw_metadata={
                "node_id": self.node_id,
                "request_id": resp.headers.get("X-Request-Id", ""),
                "node_latency_ms": resp.headers.get("X-TTS-Latency-Ms", ""),
            },
        )

    def healthz(self) -> dict:
        """GET /healthz on the worker node."""
        url = f"{self._base_url}/healthz"
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


class NodeHTTPError(Exception):
    """Raised when a TTS worker returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Node HTTP {status_code}: {detail}")
