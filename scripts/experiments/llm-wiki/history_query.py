"""Bounded previous-turn recall, layered on actual production queries."""

import re
import unicodedata


HISTORY_POLICIES = ("production", "head_tail_v1", "subject_v2", "subject_v3")
TAIL_CHARS = 200
IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[-/.]){1,5}[A-Za-z0-9]+"
    r"(?![A-Za-z0-9])"
)


def expand_history_queries(queries, current, previous, policy):
    if policy not in HISTORY_POLICIES:
        raise ValueError("Unknown history policy")
    result = list(queries)
    if policy != "production" and current and len(previous) > TAIL_CHARS:
        tail_query = previous[-TAIL_CHARS:] + "\n" + current
        if tail_query not in result:
            result.append(tail_query)
    current_identifiers = {
        match[0] for match in IDENTIFIER.finditer(unicodedata.normalize("NFKC", current))
        if re.search(r"[A-Za-z]", match[0]) and re.search(r"[0-9]", match[0])
    }
    if (policy in ("subject_v2", "subject_v3") and current
            and (policy == "subject_v2" or not current_identifiers)):
        # Require one unique identifier, not merely its last occurrence: two
        # products or a correction must remain ambiguous to retrieval.
        identifiers = {match[0] for match in IDENTIFIER.finditer(previous)
                       if re.search(r"[A-Za-z]", match[0])
                       and re.search(r"[0-9]", match[0])}
        if len(identifiers) == 1:
            subject_query = next(iter(identifiers)) + "\n" + current
            if subject_query not in result:
                result.append(subject_query)
    return result
