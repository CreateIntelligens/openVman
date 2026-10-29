"""Experimental, extractive history retention; never a fact summary.

Only user/assistant history is accepted. Budgets count Python Unicode code points
(and 16 framing characters per message), not tokens or bytes. Full source
sentences are retained in order, with explicit markers for omissions. Identifier
matching uses NFKC only for detection; returned source text is never normalized.

This is a conservative lexical candidate, not semantic coreference resolution:
identifiers, question overlap, corrections, and nearby condition/negation cues
anchor retention. A condition stated far away without a shared term or explicit
reference can be missed. Single newlines are not reliable sentence boundaries;
long indivisible sentences can raise ValueError. It neither resolves competing
subjects nor validates assistant claims. Consumers must keep roles and treat
omitted context as unknown. No production module or runtime configuration is
imported or changed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any
import unicodedata


MESSAGE_OVERHEAD = 16
OMISSION = "\n[...前文省略...]\n"
_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[-/._][A-Za-z0-9]+)*"
    r"(?![A-Za-z0-9])"
)
_GUARD = re.compile(
    r"不|未|無|非|否|禁止|只有|僅|限|必須|需要|除非|如果|若|前提|條件|才|"
    r"之前|之後|改口|更正|改成|應為|別|尚|可能|"
    r"\b(?:not|no|never|only|unless|except|if|provided|before|after|"
    r"instead|correction|actually|must|cannot|without|pending|may|might)\b|"
    r"\b(?:can|won|is|does|did)n['’]t\b",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
    r"改口|更正|改成|應為|說錯|寫錯|前述.{0,8}有誤|不是.{0,80}而是|"
    r"\b(?:correction|correcting|instead|actually|i meant)\b",
    re.IGNORECASE,
)
_SUBJECT_DECLARATION = re.compile(
    r"(?:這次|這一輪|本輪|本次|目前|現在).{0,24}"
    r"(?:主題|對象|項目|服務|型號|科別)(?:是|為|[:：])\s*(?!什麼|哪|誰)"
    r"|\b(?:the |our |current )?(?:topic|subject|item|service|model)\s+(?:is|:)\s+"
    r"|\b(?:el |nuestro )?(?:tema|asunto|modelo)\s+es\s+",
    re.IGNORECASE,
)
_REFERENCE = re.compile(
    r"它|該|此款|上述|前述|這款|那款|其|\b(?:it|this|that|above)\b",
    re.IGNORECASE,
)
_STOP_WORDS = {"the", "this", "that", "does", "what", "which", "with", "have"}


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _terms(text: str) -> set[str]:
    normalized = _normalized(text)
    terms = {
        token for token in re.findall(r"[a-z0-9][a-z0-9._/-]+", normalized)
        if token not in _STOP_WORDS
    }
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        terms.update(run[index:index + 2] for index in range(len(run) - 1))
    return terms


def _has_identifier(text: str) -> bool:
    return any(
        re.search(r"[a-z]", token[0]) and re.search(r"[0-9]", token[0])
        for token in _IDENTIFIER.finditer(_normalized(text))
    )


def _sentences(text: str) -> list[tuple[int, int]]:
    """Keep decimals/model punctuation and single-line wraps inside a sentence."""
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        terminal = char in "。！？!?"
        if char in ".．":
            # A period inside a decimal or an identifier is not a terminator.
            terminal = not (
                index and index + 1 < len(text)
                and text[index - 1].isascii() and text[index - 1].isalnum()
                and text[index + 1].isascii() and text[index + 1].isalnum()
            )
            if (index and index + 1 < len(text)
                    and text[index - 1].isdecimal()
                    and text[index + 1].isdecimal()):
                terminal = False
            # Fullwidth letters/digits must receive the same protection.
            if (index and index + 1 < len(text)
                    and re.fullmatch(r"[a-z0-9]", _normalized(text[index - 1]))
                    and re.fullmatch(r"[a-z0-9]", _normalized(text[index + 1]))):
                terminal = False
        paragraph_end = char == "\n" and index + 1 < len(text) and text[index + 1] == "\n"
        if terminal or paragraph_end:
            end = index + 1
            while end < len(text) and text[end] in "。！？!?\"'」』）)] \t\r\n":
                end += 1
            spans.append((start, end))
            start = end
            index = end
        else:
            index += 1
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _render(text: str, spans: list[tuple[int, int]], kept: set[int]) -> str:
    chunks: list[str] = []
    end = 0
    for index in sorted(kept):
        start, stop = spans[index]
        if start > end:
            chunks.append(OMISSION)
        chunks.append(text[start:stop])
        end = stop
    if end < len(text):
        chunks.append(OMISSION)
    return "".join(chunks)


def _compress(text: str, question: str, budget: int, *, retain_subject_declarations: bool) -> str:
    if len(text) <= budget:
        return text
    spans = _sentences(text)
    parts = [text[start:end] for start, end in spans]
    normalized = [_normalized(part) for part in parts]
    question_terms = _terms(question)
    overlap = [len(question_terms & _terms(part)) for part in parts]
    subjects = {index for index, part in enumerate(parts) if _has_identifier(part)}
    if retain_subject_declarations:
        declared = {part.strip(): index for index, part in enumerate(normalized)
                    if _SUBJECT_DECLARATION.search(part)}
        subjects.update(declared.values())
    corrections = {
        index for index, part in enumerate(normalized)
        if _CORRECTION.search(part) and (
            index in subjects or overlap[index]
            or re.match(r"^\s*(?:改口|更正|說錯|寫錯|不是|correction|actually|i meant)", part)
        )
    }
    guards = {index for index, part in enumerate(normalized) if _GUARD.search(part)}

    # Repetition in background prose must not consume the entire safety budget.
    # Only the last identical, independently relevant guard becomes an anchor;
    # occurrences next to a subject/correction are retained independently below.
    relevant_guards: dict[str, int] = {}
    for index in sorted(guards):
        if overlap[index] >= 2 or (overlap[index] and _REFERENCE.search(normalized[index])):
            relevant_guards[normalized[index].strip()] = index
    required = subjects | corrections | set(relevant_guards.values())
    for index in sorted(subjects | corrections):
        required.update(
            neighbor for neighbor in (index - 1, index + 1) if neighbor in guards
        )

    def with_context(indices: set[int]) -> set[int]:
        result = set(indices)
        nearby_guards = indices & guards
        for index in indices:
            nearby_guards.update(
                neighbor for neighbor in (index - 1, index + 1)
                if neighbor in guards
            )
        result.update(nearby_guards)
        for index in nearby_guards:
            # An assertion can depend on an adjacent condition; the condition
            # can itself depend on a premise or following consequence.
            result.update(
                neighbor for neighbor in (index - 1, index + 1)
                if 0 <= neighbor < len(spans)
            )
        return result

    required = with_context(required)
    if not required:
        # Never fabricate a fragment when even one original sentence cannot fit.
        ranked = sorted(range(len(parts)), key=lambda i: (overlap[i], i), reverse=True)
        for index in ranked:
            trial = with_context({index})
            if len(_render(text, spans, trial)) <= budget:
                required = trial
                break
    if not required or len(_render(text, spans, required)) > budget:
        raise ValueError("Required complete history sentences exceed the message budget")

    kept = set(required)
    # Give the original head/tail a chance before spending remaining capacity on
    # extra lexical matches. Every addition includes its nearby safety context.
    ranked = [0, len(parts) - 1] + sorted(
        range(len(parts)), key=lambda i: (overlap[i], i), reverse=True,
    )
    for index in ranked:
        trial = with_context(kept | {index})
        if len(_render(text, spans, trial)) <= budget:
            kept = trial
    return _render(text, spans, kept)


def select_recent_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    current_question: str,
    max_messages: int,
    history_budget: int,
    message_budget: int = 600,
    retain_subject_declarations: bool = True,
) -> list[dict[str, str]]:
    """Return chronological, separately attributed source excerpts.

    The most recent nonempty user message takes budget priority, even if the
    history ends with an assistant. Other recent messages may be omitted whole
    when they cannot fit. An indivisible required user excerpt raises ValueError
    instead of being cut or silently discarded. With assistant-only input the
    latest assistant receives the same guarantee. No input object is mutated.
    """
    for name, value in (
        ("max_messages", max_messages),
        ("history_budget", history_budget),
        ("message_budget", message_budget),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if max_messages == 0:
        return []
    records: list[tuple[int, str, str]] = []
    for index, message in enumerate(messages):
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        role = str(message.get("role", ""))
        if role not in {"user", "assistant"}:
            raise ValueError("History roles must be user or assistant")
        records.append((index, role, content))
    if not records:
        return []
    anchor = next((item for item in reversed(records) if item[1] == "user"), records[-1])
    candidates = records[-max_messages:]
    if anchor not in candidates:
        candidates = sorted([anchor, *candidates[1:]])
    budget = min(message_budget, history_budget - MESSAGE_OVERHEAD)
    anchor_content = _compress(anchor[2], current_question, budget,
                               retain_subject_declarations=retain_subject_declarations)
    selected = {anchor[0]: {"role": anchor[1], "content": anchor_content}}
    used = len(anchor_content) + MESSAGE_OVERHEAD
    for index, role, content in reversed(candidates):
        if index == anchor[0]:
            continue
        remaining = min(message_budget, history_budget - used - MESSAGE_OVERHEAD)
        if remaining <= 0:
            continue
        try:
            compressed = _compress(content, current_question, remaining,
                                   retain_subject_declarations=retain_subject_declarations)
        except ValueError:
            continue
        selected[index] = {"role": role, "content": compressed}
        used += len(compressed) + MESSAGE_OVERHEAD
    return [selected[index] for index in sorted(selected)]
