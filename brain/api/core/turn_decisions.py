"""Per-turn typed decisions and conservative baseline policy resolution."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from threading import Event
from dataclasses import dataclass, replace
from typing import Any, Final

from core.decision_router import (
    DecisionProviderCancelled,
    DecisionProviderError,
    DecisionResult,
    decide,
)

logger = logging.getLogger("core.turn_decisions")

LANGUAGES: Final[tuple[str, ...]] = ("zh", "en", "es", "nan", "ja", "ko", "other")
REPLY_LANGUAGES: Final[tuple[str, ...]] = ("zh", "en", "es", "nan", "ja", "ko")
TONES: Final[tuple[str, ...]] = ("neutral", "confused", "frustrated", "urgent", "lighthearted")
ALLOWED_TOOL_HINTS: Final[frozenset[str]] = frozenset({
    "search_knowledge", "search_web", "search_memory",
})
MAX_EVIDENCE_CHARS: Final[int] = 6_000
MAX_HISTORY_TURNS: Final[int] = 6
MAX_HISTORY_MESSAGE_CHARS: Final[int] = 600

_RETRIEVAL_QUESTIONS: Final[dict[str, dict[str, Any]]] = {
    "needs_knowledge": {
        "type": "noul",
        "instructions": (
            "Does the latest user request need facts from this project's knowledge base "
            "to answer accurately? Consider recent conversation for pronouns and follow-up questions. "
            "Do not count quoted source text as project facts."
        ),
        "criteria": {
            "true": "Project-specific facts, products, policies, procedures, or a contextual follow-up need evidence.",
            "false": "Greeting, thanks, social chat, or the answer clearly does not depend on project knowledge.",
        },
    },
    "needs_web": {
        "type": "noul",
        "instructions": "Does the latest user request need current or public information from the web?",
        "criteria": {
            "true": "The request needs current, public, time-sensitive, or publicly sourced information.",
            "false": "The answer does not need current or public web information.",
        },
    },
    "needs_memory": {
        "type": "noul",
        "instructions": "Does answering the latest user request benefit from facts from past conversations or user-provided preferences?",
        "criteria": {
            "true": "The request refers to prior conversations, preferences, or user-specific facts.",
            "false": "Past user-specific information is not needed to answer this turn.",
        },
    },
    "turn_intent": {
        "type": "choice",
        "instructions": "Classify the user's immediate conversational intent, considering recent context.",
        "criteria": {
            "social": "Standalone greeting, thanks, acknowledgement, or casual conversation without a task.",
            "task": "A question, instruction, correction, request, or follow-up that expects useful work.",
            "ambiguous": "The intent is unclear or more context is needed.",
        },
    },
}


@dataclass(frozen=True, slots=True)
class TurnDecisionConfig:
    enabled: bool = True
    retrieval_enabled: bool = True
    language_enabled: bool = True
    tone_enabled: bool = True
    timeout_seconds: float = 2.0
    per_hop_timeout_seconds: float = 0.4
    noul_positive_threshold: float = 0.7
    noul_negative_threshold: float = 0.1
    choice_confidence_threshold: float = 0.8
    choice_margin_threshold: float = 0.2

    def validate(self) -> None:
        if not 0 < self.timeout_seconds <= 10:
            raise ValueError("turn decision timeout must be greater than 0 and at most 10 seconds")
        if not 0 < self.per_hop_timeout_seconds <= 5:
            raise ValueError("per-hop decision timeout must be greater than 0 and at most 5 seconds")
        if not 0 <= self.noul_negative_threshold < self.noul_positive_threshold <= 1:
            raise ValueError("noul decision thresholds must be ordered between 0 and 1")
        if not 0.5 <= self.choice_confidence_threshold <= 1:
            raise ValueError("choice confidence threshold must be between 0.5 and 1")
        if not 0 <= self.choice_margin_threshold <= 1:
            raise ValueError("choice margin threshold must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class TurnPolicy:
    needs_knowledge: bool | None = None
    needs_web: bool | None = None
    needs_memory: bool | None = None
    force_knowledge_search: bool | None = None
    auto_recall: bool | None = None
    input_languages: tuple[str, ...] = ()
    dominant_language: str | None = None
    mixed_languages: bool | None = None
    requested_response_language: str | None = None
    retrieval_language: str | None = None
    response_language: str | None = None
    turn_intent: str | None = None
    tone: str | None = None

    def to_prompt_fields(self) -> dict[str, Any]:
        """Return fixed server-owned policy codes, never the source text."""
        return {
            "needs_knowledge": self.needs_knowledge,
            "needs_web": self.needs_web,
            "needs_memory": self.needs_memory,
            "input_languages": list(self.input_languages),
            "dominant_language": self.dominant_language,
            "mixed_languages": self.mixed_languages,
            "requested_response_language": self.requested_response_language,
            "retrieval_language": self.retrieval_language,
            "response_language": self.response_language,
            "turn_intent": self.turn_intent,
            "tone": self.tone,
        }


@dataclass(frozen=True, slots=True)
class TurnDecision:
    turn_id: str
    policy: TurnPolicy
    source: str
    provider: str = ""
    hop_id: str = ""
    model: str = ""
    dependency_unavailable: bool = False
    debug_signals: tuple[dict[str, Any], ...] | None = None
    elapsed_ms: float = 0.0

    def to_debug_payload(self) -> dict[str, Any]:
        """Opt-in, transient diagnostics: fixed codes and scores only."""
        return {
            "turn_id": self.turn_id,
            "status": "fallback" if self.dependency_unavailable else "disabled" if self.source == "baseline" else "available",
            "provider": self.provider or self.source,
            "hop_id": self.hop_id,
            "model": self.model,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "signals": list(self.debug_signals or ()),
            "policy": self.policy.to_prompt_fields(),
        }


def turn_decision_config(settings: Any) -> TurnDecisionConfig:
    config = TurnDecisionConfig(
        enabled=bool(getattr(settings, "turn_decisions_enabled", True)),
        retrieval_enabled=bool(getattr(settings, "turn_decisions_retrieval_enabled", True)),
        language_enabled=bool(getattr(settings, "turn_decisions_language_enabled", True)),
        tone_enabled=bool(getattr(settings, "turn_decisions_tone_enabled", True)),
        timeout_seconds=float(getattr(settings, "turn_decisions_timeout_seconds", 2.0)),
        per_hop_timeout_seconds=float(getattr(settings, "turn_decisions_hop_timeout_seconds", 0.4)),
        noul_positive_threshold=float(getattr(settings, "turn_decisions_noul_positive_threshold", 0.7)),
        noul_negative_threshold=float(getattr(settings, "turn_decisions_noul_negative_threshold", 0.1)),
        choice_confidence_threshold=float(getattr(settings, "turn_decisions_choice_confidence_threshold", 0.8)),
        choice_margin_threshold=float(getattr(settings, "turn_decisions_choice_margin_threshold", 0.2)),
    )
    config.validate()
    return config


def build_turn_questions(
    *,
    retrieval_enabled: bool = True,
    language_enabled: bool = True,
    tone_enabled: bool = True,
) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    if retrieval_enabled:
        questions.update(_RETRIEVAL_QUESTIONS)
    if language_enabled:
        questions.update({
            f"uses_{language}": {
                "type": "noul",
                "instructions": (
                    f"Does the user's own latest utterance contain substantive {language} language? "
                    "Ignore quoted material, proper names, model identifiers, and isolated brand names."
                ),
                "criteria": {
                    "true": f"The user's own words substantially use {language}.",
                    "false": f"The user's own words do not substantially use {language}.",
                },
            }
            for language in LANGUAGES
        })
        language_options = (*LANGUAGES, "undetermined")
        questions["dominant_language"] = {
            "type": "choice",
            "instructions": "Choose the predominant language of the user's own latest utterance, not quoted source text.",
            "criteria": {
                language: (
                    f"The user's own words substantially use {language}."
                    if language != "undetermined"
                    else "The language cannot be determined confidently."
                )
                for language in language_options
            },
        }
        questions["requested_response_language"] = {
            "type": "choice",
            "instructions": (
                "Did the user explicitly request a response language in the latest message? "
                "Choose that language only when the instruction is directed to the assistant, not quoted."
            ),
            "criteria": {
                **{
                    language: f"The user explicitly asks the assistant to answer in {language}."
                    for language in LANGUAGES
                },
                "none": "There is no explicit response-language request.",
            },
        }
    if tone_enabled:
        questions["tone"] = {
            "type": "choice",
            "instructions": "Classify only the observable conversational tone of the user's latest utterance.",
            "criteria": {
                "neutral": "No clear emotional or conversational style signal.",
                "confused": "The user explicitly indicates confusion or lack of understanding.",
                "frustrated": "The user explicitly expresses frustration or dissatisfaction.",
                "urgent": "The user explicitly needs a time-sensitive, immediate response.",
                "lighthearted": "The user clearly uses a playful or lighthearted tone.",
            },
        }
    return questions


def build_turn_evidence(
    user_text: str,
    history: list[dict[str, Any]],
    *,
    speech_language: str,
    project_language: str,
    available_tools: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    eligible_history = [
        {"role": str(message["role"]), "content": str(message["content"])[:MAX_HISTORY_MESSAGE_CHARS]}
        for message in history
        if message.get("role") in {"user", "assistant"}
        and isinstance(message.get("content"), str)
        and message["content"].strip()
    ]
    safe_history = eligible_history[-MAX_HISTORY_TURNS:]
    safe_user_text = user_text[:MAX_EVIDENCE_CHARS]
    history_budget = min(3_600, MAX_EVIDENCE_CHARS - len(safe_user_text))
    # Preserve the current utterance and trim the oldest history first.
    while safe_history and sum(len(item["content"]) for item in safe_history) > history_budget:
        safe_history.pop(0)
    safe_speech_language = speech_language if speech_language in (*LANGUAGES, "undetermined") else ""
    safe_project_language = project_language if project_language in LANGUAGES else "zh"
    return {
        "user_text": safe_user_text,
        "history": safe_history,
        "speech_language": safe_speech_language,
        "project_primary_language": safe_project_language,
        "supported_languages": list(LANGUAGES),
        "available_read_tools": sorted(set(available_tools) & ALLOWED_TOOL_HINTS),
    }


def resolve_turn_policy(
    answers: dict[str, dict[str, Any]],
    *,
    user_text: str,
    project_language: str,
    speech_language: str,
    config: TurnDecisionConfig,
) -> TurnPolicy:
    needs_knowledge = _noul_signal("needs_knowledge", answers, config)
    needs_web = _noul_signal("needs_web", answers, config)
    needs_memory = _noul_signal("needs_memory", answers, config)
    intent = _choice_signal("turn_intent", answers, ("social", "task", "ambiguous"), config)
    used = tuple(language for language in LANGUAGES if _noul_signal(f"uses_{language}", answers, config) is True)
    uncertain_languages = any(
        _noul_signal(f"uses_{language}", answers, config) is None
        for language in LANGUAGES
    )
    mixed = True if len(used) > 1 else False if len(used) == 1 and not uncertain_languages else None
    dominant = _choice_signal("dominant_language", answers, (*LANGUAGES, "undetermined"), config)
    if dominant == "undetermined":
        dominant = None
    requested = _choice_signal(
        "requested_response_language",
        answers,
        (*LANGUAGES, "none"),
        config,
    )
    if requested == "none":
        requested = None
    response_language = _resolve_response_language(
        requested=requested,
        dominant=dominant,
    )
    retrieval_language = _resolve_retrieval_language(
        dominant=dominant,
        user_text=user_text,
        project_language=project_language,
        speech_language=speech_language,
    )
    tone = _choice_signal("tone", answers, TONES, config)
    if tone == "neutral":
        tone = None
    # A confident negative source need can skip only that source. Uncertainty
    # preserves the existing forced-knowledge and auto-recall behavior.
    force_knowledge_search = False if needs_knowledge is False else True if needs_knowledge is True else None
    # A confident positive uses the agent's explicit search_memory read. This
    # prevents duplicate auto-recall work in the same turn; uncertainty keeps
    # the existing auto-recall baseline.
    auto_recall = False if needs_memory is not None else None
    return TurnPolicy(
        needs_knowledge=needs_knowledge,
        needs_web=needs_web,
        needs_memory=needs_memory,
        force_knowledge_search=force_knowledge_search,
        auto_recall=auto_recall,
        input_languages=used,
        dominant_language=dominant,
        mixed_languages=mixed,
        requested_response_language=requested,
        retrieval_language=retrieval_language,
        response_language=response_language,
        turn_intent=intent,
        tone=tone,
    )


def run_turn_decision(
    *,
    user_text: str,
    history: list[dict[str, Any]],
    project_id: str,
    project_language: str,
    speech_language: str,
    available_tools: tuple[str, ...] | list[str],
    config: TurnDecisionConfig,
    turn_id: str,
    cancel_event: Event | None = None,
    capture_debug: bool = False,
) -> TurnDecision:
    started = monotonic()

    def record(decision: TurnDecision) -> TurnDecision:
        decision = replace(decision, elapsed_ms=(monotonic() - started) * 1000)
        try:
            from safety.observability import get_metrics_store

            outcome = decision.policy.needs_knowledge
            get_metrics_store().increment(
                "decision_turn_total",
                source=decision.source,
                fallback=decision.dependency_unavailable,
                knowledge="skip" if outcome is False else "required" if outcome is True else "baseline",
                web=decision.policy.needs_web is True,
                memory=decision.policy.needs_memory is True,
            )
            get_metrics_store().observe(
                "decision_turn_duration_ms",
                (monotonic() - started) * 1000,
                source=decision.source,
            )
        except Exception:  # Metrics must not affect the response path.
            logger.debug("turn decision metric write failed", exc_info=True)
        return decision

    baseline = _baseline_policy(user_text, project_language, speech_language)
    groups = {
        "retrieval_enabled": config.retrieval_enabled,
        "language_enabled": config.language_enabled,
        "tone_enabled": config.tone_enabled,
    }
    questions = build_turn_questions(**groups)
    if not config.enabled or not questions:
        return record(TurnDecision(turn_id=turn_id, policy=baseline, source="baseline"))
    evidence = build_turn_evidence(
        user_text,
        history,
        speech_language=speech_language,
        project_language=project_language,
        available_tools=available_tools,
    )
    try:
        result: DecisionResult = decide(
            evidence,
            questions,
            timeout=config.timeout_seconds,
            purpose="decision_turn",
            per_hop_timeout=config.per_hop_timeout_seconds,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        policy = resolve_turn_policy(
            result.answers,
            user_text=user_text,
            project_language=project_language,
            speech_language=speech_language,
            config=config,
        )
    except DecisionProviderCancelled:
        raise
    except Exception as exc:  # The optional classification never fails the turn.
        logger.warning(
            "turn_decision_unavailable turn_id=%s error_type=%s",
            turn_id,
            type(exc).__name__,
        )
        return record(TurnDecision(
            turn_id=turn_id,
            policy=baseline,
            source="baseline",
            dependency_unavailable=True,
        ))
    return record(TurnDecision(
        turn_id=turn_id,
        policy=policy,
        source=result.provider,
        provider=result.provider,
        hop_id=result.hop_id,
        model=result.model,
        debug_signals=_debug_signals(result.answers, questions, config) if capture_debug else None,
    ))


async def run_turn_decision_async(**kwargs: Any) -> TurnDecision:
    """Run a turn decision off-loop and cancel its provider request with the turn."""
    cancel_event = Event()
    task = asyncio.create_task(asyncio.to_thread(
        run_turn_decision,
        **kwargs,
        cancel_event=cancel_event,
    ))
    try:
        return await task
    except asyncio.CancelledError:
        cancel_event.set()
        task.cancel()
        raise


def _debug_signals(
    answers: dict[str, dict[str, Any]],
    questions: dict[str, dict[str, Any]],
    config: TurnDecisionConfig,
) -> tuple[dict[str, Any], ...]:
    signals = []
    for name, question in questions.items():
        answer = answers.get(name, {})
        if question["type"] == "noul":
            signals.append({
                "id": name, "type": "noul",
                "probability_true": answer.get("noul"),
                "resolved": _noul_signal(name, answers, config),
                "accepted": _noul_signal(name, answers, config) is not None,
            })
        else:
            options = tuple(question.get("criteria", {}))
            probabilities = answer.get("probabilities", {})
            signals.append({
                "id": name, "type": "choice",
                "value": answer.get("choice") if answer.get("choice") in options else None,
                "confidence": answer.get("confidence"),
                "probabilities": {
                    key: value for key, value in probabilities.items() if key in options
                } if isinstance(probabilities, dict) else {},
                "accepted": _choice_signal(name, answers, options, config) is not None,
            })
    return tuple(signals)


def _noul_signal(
    name: str,
    answers: dict[str, dict[str, Any]],
    config: TurnDecisionConfig,
) -> bool | None:
    answer = answers.get(name)
    probability = answer.get("noul") if isinstance(answer, dict) else None
    if not isinstance(probability, (int, float)) or isinstance(probability, bool):
        return None
    if probability >= config.noul_positive_threshold:
        return True
    if probability <= config.noul_negative_threshold:
        return False
    return None


def _choice_signal(
    name: str,
    answers: dict[str, dict[str, Any]],
    allowed: tuple[str, ...],
    config: TurnDecisionConfig,
) -> str | None:
    answer = answers.get(name)
    if not isinstance(answer, dict):
        return None
    choice = answer.get("choice")
    confidence = answer.get("confidence")
    probabilities = answer.get("probabilities")
    if (
        choice not in allowed
        or not isinstance(confidence, (int, float))
        or confidence < config.choice_confidence_threshold
        or not isinstance(probabilities, dict)
    ):
        return None
    ranked = sorted(
        (
            float(probability)
            for value, probability in probabilities.items()
            if value in allowed and isinstance(probability, (int, float))
        ),
        reverse=True,
    )
    if not ranked or ranked[0] < config.choice_confidence_threshold:
        return None
    margin = ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0)
    if margin < config.choice_margin_threshold:
        return None
    return choice


def _resolve_response_language(
    *,
    requested: str | None,
    dominant: str | None,
) -> str | None:
    if requested in REPLY_LANGUAGES:
        return requested
    if requested == "other":
        return "follow_user"
    if dominant in REPLY_LANGUAGES:
        return dominant
    # Current rule behavior remains the final fallback when the batch cannot
    # identify a useful language, preserving existing explicit user text.
    return None


def _resolve_retrieval_language(
    *,
    dominant: str | None,
    user_text: str,
    project_language: str,
    speech_language: str,
) -> str:
    from memory.language_detect import LANGUAGES as DETECTED_LANGUAGES
    from memory.language_detect import TAIWANESE, detect_language

    if speech_language == TAIWANESE:
        return TAIWANESE
    if dominant in DETECTED_LANGUAGES:
        return dominant
    default = project_language if project_language in DETECTED_LANGUAGES else "zh"
    return detect_language(user_text, default)


def _baseline_policy(
    user_text: str,
    project_language: str,
    speech_language: str,
) -> TurnPolicy:
    return TurnPolicy(
        retrieval_language=_resolve_retrieval_language(
            dominant=None,
            user_text=user_text,
            project_language=project_language,
            speech_language=speech_language,
        ),
    )


__all__ = [
    "LANGUAGES",
    "REPLY_LANGUAGES",
    "TONES",
    "TurnDecision",
    "TurnDecisionConfig",
    "TurnPolicy",
    "build_turn_evidence",
    "build_turn_questions",
    "resolve_turn_policy",
    "run_turn_decision",
    "run_turn_decision_async",
    "turn_decision_config",
]
