"""Check literal claim provenance and quarantine known instruction patterns.

This is an extraction gate, not a semantic truth or general injection detector.
Supply original source units, not earlier model-generated summaries.
"""

import re
import unicodedata


LIMITATIONS = (
    "Literal support does not establish source truth, currency, or authority.",
    "Known instruction patterns are a narrow denylist, not general injection "
    "protection; unfamiliar instructions still require manual review.",
    "An entire referenced unit is quarantined when a known marker is found; "
    "clean excerpts from that same unit do not bypass quarantine.",
    "Claims must preserve complete source sentences or lines. Incomplete "
    "clauses are rejected conservatively to avoid dropping conditions.",
    "Source-unit boundaries and IDs must be assigned from original inputs; "
    "the caller remains responsible for their project and document scope.",
    "Literal extraction cannot reliably identify contradictions, misleading "
    "context across sentences, or every ambiguous model reference.",
)

INSTRUCTION_PATTERNS = (
    (
        "fake_system_role",
        re.compile(
            r"<\s*/?\s*(?:system|developer)(?:\s[^>]*|\s*)>"
            r"|\[(?:system|developer)\]"
            r"|(?:^|\n)\s*#{1,6}\s*(?:system|developer)\b"
            r"|(?:^|\n)\s*(?:system|developer)\s*[:：]",
            re.IGNORECASE,
        ),
    ),
    (
        "ignore_previous_instructions",
        re.compile(
            r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+"
            r"(?:instructions|rules|prompts)\b"
            r"|(?:忽略|無視)(?:之前|先前|以上|前面|所有)(?:的)?"
            r"(?:規則|指令|限制)",
            re.IGNORECASE,
        ),
    ),
    (
        "compiler_directive",
        re.compile(
            r"給(?:目錄生成器|編譯器|摘要生成器)(?:的)?"
            r"(?:最高優先)?指令"
            r"|(?:compiler|summary generator|index generator)"
            r"\s+(?:instruction|directive)\s*:",
            re.IGNORECASE,
        ),
    ),
    (
        "citation_directive",
        re.compile(r"(?:服從|遵從)(?:引用|來源|引文).{0,16}指令"),
    ),
    (
        "tested_poison_marker",
        re.compile(r"(?<![A-Za-z0-9_])POISON_ACCEPTED_\d+(?![A-Za-z0-9_])", re.IGNORECASE),
    ),
)
INLINE_REF_RE = re.compile(r"\[(S\d+|[^\[\]\n]+\.csv#\d+)\]")
SENTENCE_BOUNDARY_RE = re.compile(
    r"\n+|(?<=[。！？!?])|(?<=[^\d]\.)(?=\s|$)"
)
QA_LABEL_RE = re.compile(r"^(?:Q|A|問題|回答)\s*[:：]\s*")


def normalize(text):
    """Apply only NFKC and whitespace normalization; keep case and wording."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def detect_instruction(text):
    """Return known marker names without echoing source content."""
    if not isinstance(text, str):
        return []
    normalized = unicodedata.normalize("NFKC", text)
    return [
        name for name, pattern in INSTRUCTION_PATTERNS
        if pattern.search(normalized)
    ]


def _complete_excerpt(text, source):
    normalized_source = normalize(source)
    if text == normalized_source:
        return True
    # Whitespace alone is not a sentence boundary: "不 提供" must never
    # become "提供". Preserve original newlines until units are identified.
    units = SENTENCE_BOUNDARY_RE.split(
        unicodedata.normalize("NFKC", source)
    )
    starts = set()
    ends = set()
    cursor = 0
    for unit in units:
        unit = unit.strip()
        normalized = normalize(unit)
        if not normalized:
            continue
        position = normalized_source.find(normalized, cursor)
        if position < 0:
            continue
        starts.add(position)
        label = QA_LABEL_RE.match(normalized)
        if label:
            starts.add(position + label.end())
        end = position + len(normalized)
        ends.add(end)
        # Omitting a sentence terminator does not remove a condition.
        if normalized[-1] in "。！？!?":
            ends.add(end - 1)
        cursor = end
    position = normalized_source.find(text)
    while position >= 0:
        if position in starts and position + len(text) in ends:
            return True
        position = normalized_source.find(text, position + 1)
    return False


def validate_claim(text, refs, sources):
    """Return violations; an empty list means this literal claim is allowed."""
    violations = []
    if not isinstance(text, str):
        return ["invalid_text"]
    normalized = normalize(text)
    if not normalized:
        violations.append("empty_text")
    if not isinstance(refs, list) or not all(
        isinstance(ref, str) and ref for ref in refs
    ):
        return violations + ["invalid_refs"]
    if not isinstance(sources, dict):
        return violations + ["invalid_sources"]
    if not refs:
        violations.append("missing_ref")
    if len(refs) != len(set(refs)):
        violations.append("duplicate_ref")
    if len(refs) > 1:
        violations.append("multiple_sources_require_separate_claims")
    for marker in detect_instruction(text):
        violations.append("claim_instruction:" + marker)
    for inline in INLINE_REF_RE.findall(text):
        if inline not in sources or inline not in refs:
            violations.append("unverified_inline_ref:" + inline)
    for ref in dict.fromkeys(refs):
        if ref not in sources:
            violations.append("unknown_ref:" + ref)
            continue
        source = sources[ref]
        if not isinstance(source, str) or not normalize(source):
            violations.append("invalid_source:" + ref)
            continue
        for marker in detect_instruction(source):
            violations.append("source_instruction:" + ref + ":" + marker)
        if normalized not in normalize(source):
            violations.append("unsupported_text:" + ref)
        elif not _complete_excerpt(normalized, source):
            violations.append("incomplete_source_statement:" + ref)
    return violations


def validate_claims(claims, sources):
    """Validate a batch and expose the gate's limits with every result."""
    findings = []
    if not isinstance(claims, list) or not claims:
        findings.append({
            "index": -1, "violations": ["empty_or_invalid_claims"],
        })
    else:
        for index, claim in enumerate(claims):
            if not isinstance(claim, dict) or set(claim) != {"text", "refs"}:
                errors = ["invalid_claim_schema"]
            else:
                errors = validate_claim(
                    claim["text"], claim["refs"], sources,
                )
            if errors:
                findings.append({"index": index, "violations": errors})
    return {
        "valid": not findings,
        "violations": findings,
        "limitations": list(LIMITATIONS),
    }
