"""Typed decisions with an admin-configured, bounded provider fallback chain."""

from __future__ import annotations

import json
import asyncio
import logging
import math
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from config import get_settings

logger = logging.getLogger("core.decision_router")

_INTERNAL_TOKEN_HEADER: Final = "X-Internal-Token"
_CONFIG_TTL_SECONDS = 10.0
_CONFIG_TIMEOUT_SECONDS = 0.5
_MAX_QUESTIONS = 32
_MAX_DECISION_INPUT_BYTES = 64 * 1024
_EXPECTED_HOPS: Final[dict[str, tuple[str, str, str, bool]]] = {
    "clef-primary": ("clef", "https://clef.create360.ai/v1/systemone", "clef-flash", False),
    "clef-backup": ("clef", "https://clef.aiurl.tw/v1/systemone", "clef-flash", False),
    "jev": ("jev", "https://api.typesafe.ai/v1/systemone", "jev-latest", True),
    "openai": ("openai", "https://api.openai.com/v1/decisions", "gpt-6-luna", True),
}
_DEFAULT_ORDER: Final = tuple(_EXPECTED_HOPS)


class DecisionProviderError(RuntimeError):
    """No configured decision provider returned a valid typed answer."""


class DecisionProviderCancelled(RuntimeError):
    """The originating conversation turn has been cancelled or superseded."""


@dataclass(frozen=True, slots=True)
class DecisionProvider:
    id: str
    provider: str
    endpoint: str
    model: str
    api_key: str
    credential_required: bool


@dataclass(frozen=True, slots=True)
class DecisionResult:
    answers: dict[str, dict[str, Any]]
    provider: str
    hop_id: str
    model: str


@dataclass(frozen=True, slots=True)
class _ProviderConfiguration:
    providers: tuple[DecisionProvider, ...]


_CONFIG_LOCK = threading.Lock()
_CONFIG_CACHE: _ProviderConfiguration | None = None
_CONFIG_CACHE_AT = 0.0


class _WallClockHttpClient:
    """Reuse one async connection pool while enforcing an absolute sync deadline."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: httpx.AsyncClient | None = None
        self._transport = transport
        self._ready = Event()
        self._start_lock = threading.Lock()

    def _start(self) -> None:
        if self._loop is not None:
            return
        with self._start_lock:
            if self._loop is None:
                Thread(target=self._run, name="decision-http", daemon=True).start()
                self._ready.wait()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()

    async def _request(self, method: str, url: str, kwargs: dict[str, Any], timeout: float) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self._transport)
        try:
            return await asyncio.wait_for(
                self._client.request(method, url, **kwargs),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise httpx.ReadTimeout("provider wall-clock deadline exceeded") from exc

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        timeout = kwargs.pop("timeout", None)
        cancel_event = kwargs.pop("cancel_event", None)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise httpx.ReadTimeout("provider wall-clock deadline expired")
        deadline = monotonic() + float(timeout)
        self._start()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(
            self._request(method, url, kwargs, float(timeout)),
            self._loop,
        )
        while True:
            if cancel_event is not None and cancel_event.is_set():
                future.cancel()
                raise DecisionProviderCancelled("decision turn was cancelled")
            remaining = deadline - monotonic()
            if remaining <= 0:
                future.cancel()
                raise httpx.ReadTimeout("provider wall-clock deadline exceeded")
            try:
                return future.result(timeout=min(0.025, remaining) if cancel_event is not None else remaining)
            except FutureTimeoutError as exc:
                if monotonic() >= deadline:
                    future.cancel()
                    raise httpx.ReadTimeout("provider wall-clock deadline exceeded") from exc
                if cancel_event is None:
                    future.cancel()
                    raise httpx.ReadTimeout("provider wall-clock deadline exceeded") from exc

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._send("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._send("POST", url, **kwargs)


_HTTP = _WallClockHttpClient()


def decision_available() -> bool:
    try:
        return bool(_provider_configuration(timeout=_CONFIG_TIMEOUT_SECONDS).providers)
    except Exception:
        return False


def decide(
    state: str | dict[str, Any] | list[Any] | None,
    questions: dict[str, dict[str, Any]],
    *,
    timeout: float,
    purpose: str,
    per_hop_timeout: float | None = None,
    cancel_event: threading.Event | None = None,
) -> DecisionResult:
    """Evaluate typed questions in order, using one request-wide deadline."""
    normalized = _normalize_questions(questions)
    state_json = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
    questions_json = json.dumps(normalized, ensure_ascii=False)
    if len(state_json.encode("utf-8")) + len(questions_json.encode("utf-8")) > _MAX_DECISION_INPUT_BYTES:
        raise ValueError("decision input exceeds the size limit")
    if timeout <= 0:
        raise DecisionProviderError("decision deadline expired")
    if per_hop_timeout is not None and per_hop_timeout <= 0:
        raise DecisionProviderError("provider hop deadline must be positive")
    if cancel_event is not None and cancel_event.is_set():
        raise DecisionProviderCancelled("decision turn was cancelled")
    started = monotonic()
    deadline = started + timeout
    try:
        configuration = _provider_configuration(
            timeout=min(_CONFIG_TIMEOUT_SECONDS, timeout),
            cancel_event=cancel_event,
        )
    except DecisionProviderCancelled:
        raise
    except Exception as exc:
        _record_hop(
            provider="decision-router", hop_id="configuration", model="",
            purpose=purpose, elapsed_ms=(monotonic() - started) * 1000,
            status="configuration_error", usage_obj=None,
        )
        raise DecisionProviderError("decision provider configuration unavailable") from exc

    failures: list[str] = []
    for hop in configuration.providers:
        if cancel_event is not None and cancel_event.is_set():
            raise DecisionProviderCancelled("decision turn was cancelled")
        remaining = deadline - monotonic()
        if remaining <= 0:
            failures.append("deadline")
            break
        if hop.credential_required and not hop.api_key:
            failures.append(f"{hop.id}:missing_key")
            _record_hop(
                provider=hop.provider, hop_id=hop.id, model=hop.model,
                purpose=purpose, elapsed_ms=0, status="missing_key", usage_obj=None,
            )
            continue

        hop_started = monotonic()
        usage_obj: Any = None
        status = "error"
        try:
            hop_budget = min(remaining, per_hop_timeout) if per_hop_timeout is not None else remaining
            request_options: dict[str, Any] = {"timeout": hop_budget}
            if cancel_event is not None:
                request_options["cancel_event"] = cancel_event
            body = _call_provider(hop, state, normalized, **request_options)
            usage_obj = body.get("usage")
            answers = _parse_answers(hop.provider, body, normalized)
            status = "ok"
            _record_hop(
                provider=hop.provider, hop_id=hop.id, model=hop.model,
                purpose=purpose, elapsed_ms=(monotonic() - hop_started) * 1000,
                status=status, usage_obj=usage_obj,
            )
            return DecisionResult(answers, hop.provider, hop.id, hop.model)
        except DecisionProviderCancelled:
            _record_hop(
                provider=hop.provider, hop_id=hop.id, model=hop.model,
                purpose=purpose, elapsed_ms=(monotonic() - hop_started) * 1000,
                status="cancelled", usage_obj=usage_obj,
            )
            raise
        except Exception as exc:  # Provider errors are isolated to this hop.
            status = _failure_status(exc)
            failures.append(f"{hop.id}:{status}")
            _record_hop(
                provider=hop.provider, hop_id=hop.id, model=hop.model,
                purpose=purpose, elapsed_ms=(monotonic() - hop_started) * 1000,
                status=status, usage_obj=usage_obj,
            )
            logger.warning(
                "decision_provider_failed hop=%s status=%s purpose=%s",
                hop.id, status, purpose,
            )

    raise DecisionProviderError("all decision providers failed: " + ",".join(failures))


def decide_nouls(
    state: str | dict[str, Any] | list[Any] | None,
    questions: dict[str, dict[str, Any]],
    *,
    timeout: float,
    purpose: str,
) -> dict[str, float]:
    typed = {
        name: {"type": "noul", **question}
        for name, question in questions.items()
    }
    result = decide(state, typed, timeout=timeout, purpose=purpose)
    return {name: float(answer["noul"]) for name, answer in result.answers.items()}


def decide_noul(
    state: str | dict[str, Any] | list[Any] | None,
    question: dict[str, Any],
    *,
    timeout: float,
    purpose: str,
) -> float:
    return decide_nouls(state, {"q": question}, timeout=timeout, purpose=purpose)["q"]


def _provider_configuration(
    *, timeout: float, cancel_event: threading.Event | None = None,
) -> _ProviderConfiguration:
    global _CONFIG_CACHE, _CONFIG_CACHE_AT
    now = monotonic()
    with _CONFIG_LOCK:
        if _CONFIG_CACHE is not None and now - _CONFIG_CACHE_AT < _CONFIG_TTL_SECONDS:
            return _CONFIG_CACHE
    try:
        loaded = _fetch_provider_configuration(timeout=timeout, cancel_event=cancel_event)
    except DecisionProviderCancelled:
        raise
    except Exception:
        with _CONFIG_LOCK:
            if _CONFIG_CACHE is not None:
                _CONFIG_CACHE_AT = monotonic()
                return _CONFIG_CACHE
        raise DecisionProviderError("decision provider configuration unavailable")
    with _CONFIG_LOCK:
        _CONFIG_CACHE = loaded
        _CONFIG_CACHE_AT = monotonic()
    return loaded


def _fetch_provider_configuration(
    *, timeout: float, cancel_event: threading.Event | None = None,
) -> _ProviderConfiguration:
    cfg = get_settings()
    if not cfg.gateway_internal_token or not cfg.gateway_base_url:
        raise DecisionProviderError("internal decision configuration is unavailable")
    request: dict[str, Any] = {
        "headers": {_INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
        "timeout": timeout,
    }
    if cancel_event is not None:
        request["cancel_event"] = cancel_event
    response = _HTTP.get(
        f"{cfg.gateway_base_url.rstrip('/')}/api/v1/internal/decision-providers",
        **request,
    )
    response.raise_for_status()
    return _parse_runtime_configuration(response.json())


def _parse_runtime_configuration(body: Any) -> _ProviderConfiguration:
    if not isinstance(body, dict) or not isinstance(body.get("providers"), list):
        raise DecisionProviderError("invalid decision provider configuration")
    providers: list[DecisionProvider] = []
    seen: set[str] = set()
    for raw in body["providers"]:
        if not isinstance(raw, dict):
            raise DecisionProviderError("invalid decision provider entry")
        hop_id_value = raw.get("id")
        if not isinstance(hop_id_value, str):
            raise DecisionProviderError("unknown or duplicate decision provider")
        hop_id = hop_id_value
        expected = _EXPECTED_HOPS.get(hop_id)
        if expected is None or hop_id in seen:
            raise DecisionProviderError("unknown or duplicate decision provider")
        provider, endpoint, model, required = expected
        api_key = raw.get("api_key", "")
        endpoint_value = raw.get("endpoint")
        if not isinstance(endpoint_value, str):
            raise DecisionProviderError("invalid decision provider configuration")
        endpoint = endpoint_value
        endpoint_valid = endpoint == expected[1]
        if provider == "jev":
            endpoint_valid = (
                urlsplit(endpoint).scheme == "https"
                and endpoint.rstrip("/").endswith("/v1/systemone")
            )
        if (
            raw.get("provider") != provider
            or not endpoint_valid
            or raw.get("model") != model
            or raw.get("credential_required") is not required
            or not isinstance(api_key, str)
            or len(api_key) > 4096
        ):
            raise DecisionProviderError("invalid decision provider configuration")
        seen.add(hop_id)
        providers.append(DecisionProvider(hop_id, provider, endpoint, model, api_key, required))
    if body.get("order") != [provider.id for provider in providers]:
        raise DecisionProviderError("provider order does not match provider entries")
    return _ProviderConfiguration(tuple(providers))


def _normalize_questions(questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(questions, dict) or not questions or len(questions) > _MAX_QUESTIONS:
        raise ValueError("decision questions must contain between 1 and 32 items")
    normalized: dict[str, dict[str, Any]] = {}
    for name, question in questions.items():
        if not isinstance(name, str) or not name or len(name) > 128 or not isinstance(question, dict):
            raise ValueError("invalid decision question")
        question_type = question.get("type", "noul")
        if question_type not in {"noul", "choice", "score"}:
            raise ValueError("unsupported decision question type")
        instructions = question.get("instructions")
        if instructions is not None and not isinstance(instructions, str):
            raise ValueError("decision instructions must be text")
        criteria = question.get("criteria")
        if question_type == "noul":
            if criteria is not None and (
                not isinstance(criteria, dict)
                or any(not isinstance(value, str) for value in criteria.values())
            ):
                raise ValueError("noul criteria must map labels to text")
        elif question_type == "choice":
            if (
                not isinstance(criteria, dict)
                or len(criteria) < 2
                or len(criteria) > 255
                or any(not isinstance(value, str) for value in criteria.values())
            ):
                raise ValueError("choice questions require 2 to 255 text criteria")
        elif (
            not isinstance(criteria, list)
            or not 2 <= len(criteria) <= 10
            or any(
                not isinstance(level, str)
                and not (
                    isinstance(level, dict)
                    and isinstance(level.get("label") or level.get("value"), str)
                    and isinstance(level.get("description", ""), str)
                )
                for level in criteria
            )
        ):
            raise ValueError("score questions require 2 to 10 text levels")
        normalized[name] = {**question, "type": question_type}
    return normalized


def _call_provider(
    hop: DecisionProvider,
    state: str | dict[str, Any] | list[Any] | None,
    questions: dict[str, dict[str, Any]],
    *,
    timeout: float,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if hop.provider == "openai":
        payload = _openai_payload(hop, state, questions)
    else:
        payload = {
            "state": state,
            "model": hop.model,
            "questions": questions,
        }
    headers = {"Content-Type": "application/json"}
    if hop.api_key:
        headers["Authorization"] = f"Bearer {hop.api_key}"
    request: dict[str, Any] = {"json": payload, "headers": headers, "timeout": timeout}
    if cancel_event is not None:
        request["cancel_event"] = cancel_event
    response = _HTTP.post(hop.endpoint, **request)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("provider response must be an object")
    return body


def _openai_payload(
    hop: DecisionProvider,
    state: str | dict[str, Any] | list[Any] | None,
    questions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    input_value = state if isinstance(state, str) or state is None else json.dumps(state, ensure_ascii=False)
    mapped: list[dict[str, Any]] = []
    for name, question in questions.items():
        question_type = question["type"]
        instructions = question.get("instructions") or name
        criteria = question.get("criteria")
        item: dict[str, Any] = {
            "name": name,
            "type": "predicate" if question_type == "noul" else question_type,
            "instructions": _instructions_with_criteria(instructions, criteria)
            if question_type == "noul" else instructions,
        }
        if question_type == "choice":
            if not isinstance(criteria, dict) or len(criteria) < 2:
                raise ValueError("choice questions require at least two criteria")
            item["choices"] = [
                {"value": str(value), "description": str(description or "")}
                for value, description in criteria.items()
            ]
        elif question_type == "score":
            if not isinstance(criteria, list) or len(criteria) < 2:
                raise ValueError("score questions require at least two criteria")
            item["levels"] = [_score_level(value, index) for index, value in enumerate(criteria)]
        mapped.append(item)
    return {"model": hop.model, "input": input_value, "questions": mapped}


def _instructions_with_criteria(instructions: Any, criteria: Any) -> str:
    text = str(instructions)
    if isinstance(criteria, dict):
        details = "; ".join(f"{key}: {value}" for key, value in criteria.items())
        if details:
            return f"{text}\n判斷標準：{details}"
    return text


def _score_level(value: Any, index: int) -> dict[str, str]:
    if isinstance(value, dict):
        label = value.get("label") or value.get("value") or str(index)
        description = value.get("description") or value.get("instructions") or ""
        return {"label": str(label), "description": str(description)}
    return {"label": str(value), "description": ""}


def _parse_answers(
    provider: str,
    body: dict[str, Any],
    questions: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    answers: dict[str, dict[str, Any]] = {}
    if provider == "openai":
        raw_answers = body.get("answers")
        if not isinstance(raw_answers, list):
            raise ValueError("OpenAI Decisions response is missing answers")
        for answer in raw_answers:
            if not isinstance(answer, dict) or answer.get("type") == "refusal":
                raise ValueError("provider refused or malformed a decision")
            name = answer.get("name")
            if name in questions:
                answers[name] = _normalize_openai_answer(answer, questions[name])
    else:
        raw_answers = body.get("answers")
        if not isinstance(raw_answers, dict):
            raise ValueError("System One response is missing answers")
        for name, question in questions.items():
            answer = raw_answers.get(name)
            if not isinstance(answer, dict):
                raise ValueError("System One response omitted a requested answer")
            answers[name] = _normalize_systemone_answer(answer, question)
    if set(answers) != set(questions):
        raise ValueError("provider response did not answer every question")
    return answers


def _normalize_systemone_answer(answer: dict[str, Any], question: dict[str, Any]) -> dict[str, Any]:
    answer_type = question["type"]
    if answer.get("type") not in (None, answer_type):
        raise ValueError("System One returned an unexpected answer type")
    if answer_type == "noul":
        value = _probability(answer.get("noul"))
        return {"type": "noul", "noul": value}
    if answer_type == "choice":
        choice = answer.get("choice")
        if not isinstance(choice, str) or choice not in question.get("criteria", {}):
            raise ValueError("System One returned an unknown choice")
        return {
            "type": "choice", "choice": choice,
            "confidence": _probability(answer.get("confidence")),
            "probabilities": _probability_map(answer.get("probabilities")),
        }
    score = answer.get("score")
    maximum = len(question["criteria"]) - 1
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0 <= score <= maximum
    ):
        raise ValueError("System One returned an invalid score")
    return {"type": "score", "score": float(score)}


def _normalize_openai_answer(answer: dict[str, Any], question: dict[str, Any]) -> dict[str, Any]:
    question_type = question["type"]
    expected = "predicate" if question_type == "noul" else question_type
    if answer.get("type") != expected:
        raise ValueError("OpenAI Decisions returned an unexpected answer type")
    if question_type == "noul":
        return {"type": "noul", "noul": _probability(answer.get("probability"))}
    if question_type == "choice":
        choice = answer.get("choice")
        if not isinstance(choice, str) or choice not in question.get("criteria", {}):
            raise ValueError("OpenAI Decisions returned an unknown choice")
        return {
            "type": "choice", "choice": choice,
            "confidence": _probability(answer.get("confidence")),
            "probabilities": _openai_probability_map(answer.get("probabilities")),
        }
    score = answer.get("score")
    maximum = len(question["criteria"]) - 1
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0 <= score <= maximum
    ):
        raise ValueError("OpenAI Decisions returned an invalid score")
    return {
        "type": "score", "score": float(score),
        "confidence": _probability(answer.get("confidence")),
    }


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("decision probability must be numeric")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("decision probability must be between 0 and 1")
    return float(value)


def _probability_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ValueError("decision probabilities are missing")
    return {str(key): _probability(probability) for key, probability in value.items()}


def _openai_probability_map(value: Any) -> dict[str, float]:
    if not isinstance(value, list) or not value:
        raise ValueError("decision probabilities are missing")
    result: dict[str, float] = {}
    for item in value:
        if not isinstance(item, dict) or "value" not in item:
            raise ValueError("invalid OpenAI probability entry")
        result[str(item["value"])] = _probability(item.get("probability"))
    return result


def _failure_status(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection_error"
    if isinstance(exc, httpx.HTTPStatusError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", "unknown")
        return f"http_{status_code}"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, ValueError):
        return "invalid_response"
    if isinstance(exc, httpx.RequestError):
        return "request_error"
    return "provider_error"


def _record_hop(
    *,
    provider: str,
    hop_id: str,
    model: str,
    purpose: str,
    elapsed_ms: float,
    status: str,
    usage_obj: Any,
) -> None:
    from core.usage import LLMUsage
    from infra.usage_ledger import record_usage_event

    input_tokens = _usage_int(usage_obj, "input_tokens")
    output_tokens = _usage_int(usage_obj, "output_tokens")
    record_usage_event(
        provider=provider,
        model=model or hop_id,
        usage=LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        latency_ms=elapsed_ms,
        kind=f"decision_{purpose}",
        raw={"hop_id": hop_id, "status": status},
    )


def _usage_int(usage: Any, key: str) -> int:
    if not isinstance(usage, dict):
        return 0
    value = usage.get(key, 0)
    return value if isinstance(value, int) and value >= 0 else 0


def clear_provider_configuration_cache() -> None:
    """Clear process-local runtime configuration cache (tests and admin refresh)."""
    global _CONFIG_CACHE, _CONFIG_CACHE_AT
    with _CONFIG_LOCK:
        _CONFIG_CACHE = None
        _CONFIG_CACHE_AT = 0.0


__all__ = [
    "DecisionProviderError",
    "DecisionResult",
    "decide",
    "decide_noul",
    "decide_nouls",
    "decision_available",
]
