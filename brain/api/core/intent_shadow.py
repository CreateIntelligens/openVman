"""Bounded, observational intent scoring; never selects the chat route."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
import random
from threading import BoundedSemaphore
from time import monotonic
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)
MAX_MESSAGE_CHARS = 1024
MAX_HISTORY_MESSAGES = 4
MAX_HISTORY_CHARS = 256
PROTOTYPE_VERSION = "intent-centroid-v1"
PROTOTYPES = {
    "chat": (
        "嗨，祝你有美好的一天！",
        "真開心可以和你分享生活中的小事。",
        "多謝你的協助，再見。",
    ),
    "knowledge": (
        "依公司內部規章，新進員工如何申請門禁卡？",
        "請查本專案技術文件中的部署架構。",
        "本中心的到宅服務需要準備哪些申請文件？",
    ),
    "web": (
        "請搜尋今日國際股市最新消息。",
        "請開啟 https://example.org/ 並摘要該網頁。",
        "請查交通部網站目前公布的最新交通管制資訊。",
    ),
    "clarify": (
        "請處理那個東西。",
        "他現在怎樣了？",
        "我要問一下這件事。",
    ),
}


def bounded_state(message: str, history: list[dict]) -> dict:
    return {
        "history": [
            {"role": row["role"], "content": str(row.get("content", ""))[:MAX_HISTORY_CHARS]}
            for row in history[-MAX_HISTORY_MESSAGES:]
            if row.get("role") in {"user", "assistant"}
        ],
        "message": message[:MAX_MESSAGE_CHARS],
    }


def _serialize(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def _unit(vector: list, dimension: int) -> list[float]:
    if len(vector) != dimension or any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) for value in vector
    ):
        raise ValueError("Invalid embedding vector")
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm or not math.isfinite(norm):
        raise ValueError("Invalid embedding norm")
    return [value / norm for value in vector]


class EmbeddingIntentClassifier:
    def __init__(self, cfg: Any) -> None:
        from memory.embedder import GatewayRemoteTextEmbedder

        self.adapter = GatewayRemoteTextEmbedder(
            base_url=cfg.resolved_embedding_service_url,
            api_key=cfg.embedding_service_token,
            timeout=cfg.intent_shadow_timeout_seconds,
            expected_model=cfg.embedding_expected_model,
            expected_dimension=cfg.embedding_expected_dimension,
            max_retries=0,
        )
        self.required_identity = cfg.resolve_embedding_identity(
            "bge", input_semantics="symmetric",
        )
        self.dimension = cfg.embedding_expected_dimension
        self.identity = ""
        self.centroids: dict[str, list[float]] = {}

    def close(self) -> None:
        self.adapter.close()

    def classify(self, message: str, history: list[dict]) -> dict:
        try:
            return self._classify(message, history)
        except Exception:
            # Do not reuse centroids after service identity/contract failures.
            self.identity = ""
            self.centroids = {}
            raise

    def _load_centroids(self) -> None:
        texts = [
            _serialize(bounded_state(text, []))
            for examples in PROTOTYPES.values() for text in examples
        ]
        vectors, spec, _ = self.adapter.encode_with_metadata(
            texts, input_type="symmetric",
            forced_identity=self.required_identity,
        )
        if (len(vectors) != len(texts)
                or spec.get("identity") != self.required_identity):
            raise ValueError("Invalid prototype embedding contract")
        # Validate every member before averaging; NaN must not pick a label.
        for vector in vectors:
            _unit(vector, self.dimension)
        centroids = {}
        offset = 0
        for label, examples in PROTOTYPES.items():
            group = vectors[offset:offset + len(examples)]
            centroid = [sum(column) / len(group) for column in zip(*group)]
            centroids[label] = _unit(centroid, self.dimension)
            offset += len(examples)
        self.centroids = centroids
        self.identity = spec["identity"]

    def _classify(self, message: str, history: list[dict]) -> dict:
        if not self.centroids:
            self._load_centroids()
        vectors, spec, _ = self.adapter.encode_with_metadata(
            [_serialize(bounded_state(message, history))],
            input_type="symmetric", forced_identity=self.identity,
        )
        if len(vectors) != 1 or spec.get("identity") != self.identity:
            raise ValueError("Query embedding identity drift")
        query = _unit(vectors[0], self.dimension)
        scores = {
            label: sum(a * b for a, b in zip(query, centroid))
            for label, centroid in self.centroids.items()
        }
        ranked = sorted(scores, key=scores.__getitem__, reverse=True)
        best, runner_up = ranked[:2]
        return {
            "suggestion": best,
            "scores": scores,
            "margin": scores[best] - scores[runner_up],
            "embedding_identity": self.identity,
            "prototype_version": PROTOTYPE_VERSION,
        }


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intent-shadow")
_slot = BoundedSemaphore(1)
_classifier: EmbeddingIntentClassifier | None = None
_classifier_key: tuple | None = None
_cooldown_until = 0.0


def _record(status: str, **fields: Any) -> None:
    from safety.observability import get_metrics_store

    store = get_metrics_store()
    store.increment(
        "intent_shadow_total", status=status,
        suggestion=fields.get("suggestion", "none"),
    )
    if "elapsed_ms" in fields:
        store.observe("intent_shadow_duration_ms", fields["elapsed_ms"], status=status)
    if status in {"ok", "error"}:
        logger.info(json.dumps(
            {"event": "intent_shadow", "status": status, **fields},
            ensure_ascii=False, sort_keys=True,
        ))


def _work(cfg: Any, state: dict, fields: dict) -> None:
    global _classifier, _classifier_key, _cooldown_until
    started = monotonic()
    try:
        key = (
            cfg.resolved_embedding_service_url, cfg.embedding_service_token,
            cfg.embedding_expected_model, cfg.embedding_expected_dimension,
            cfg.intent_shadow_timeout_seconds,
            cfg.resolve_embedding_identity("bge", input_semantics="symmetric"),
        )
        if _classifier is None or key != _classifier_key:
            if _classifier is not None:
                _classifier.close()
            _classifier = EmbeddingIntentClassifier(cfg)
            _classifier_key = key
        result = _classifier.classify(state["message"], state["history"])
        _record("ok", **fields, **result, elapsed_ms=(monotonic() - started) * 1000)
    except Exception as exc:
        _cooldown_until = monotonic() + cfg.intent_shadow_cooldown_seconds
        # Exception messages may contain service responses; record only the type.
        _record("error", **fields, error_type=type(exc).__name__,
                elapsed_ms=(monotonic() - started) * 1000)
    finally:
        _slot.release()


def submit_intent_shadow(
    *, message: str, history: list[dict], trace_id: str,
    project_id: str, actual_route: str,
) -> bool:
    """Try once, without waiting or queuing. The result never returns to chat."""
    cfg = get_settings()
    if getattr(cfg, "intent_shadow_enabled", False) is not True:
        return False
    if random.random() >= cfg.intent_shadow_sample_rate:
        _record("sampled_out")
        return False
    if not _slot.acquire(blocking=False):
        _record("busy")
        return False
    try:
        if monotonic() < _cooldown_until:
            _record("cooldown")
            _slot.release()
            return False
        state = bounded_state(message, history)
        fields = {
            "trace_id": trace_id, "project_id": project_id,
            "actual_route": actual_route,
            "force_knowledge_search": cfg.chat_force_knowledge_search,
            "input_truncated": (
                len(message) > MAX_MESSAGE_CHARS
                or len(history) > MAX_HISTORY_MESSAGES
                or any(
                    len(str(row.get("content", ""))) > MAX_HISTORY_CHARS
                    for row in history[-MAX_HISTORY_MESSAGES:]
                )
            ),
        }
        _executor.submit(_work, cfg, state, fields)
        return True
    except Exception:
        _slot.release()
        raise
