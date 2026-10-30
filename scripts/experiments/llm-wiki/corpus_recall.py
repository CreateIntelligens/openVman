"""Identical offline retrieval rules for raw units and prepared MD sections.

No model calls, text rewriting, chunk splitting or inferred facts occur here.
Callers supply current valid source refs and vectors from one embedding identity;
identity verification remains the caller's responsibility. Prepared indexes
validate document vectors once; query vectors are validated on every call.
"""

import copy
import math
from numbers import Real


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must be a nonempty string")


def _strings(value, label):
    if not isinstance(value, list) or not value:
        raise ValueError(label + " must be a nonempty list")
    for item in value:
        _text(item, label)
    if len(value) != len(set(value)):
        raise ValueError(label + " must not contain duplicates")


def _records(records):
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    seen = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("record must be a dict")
        for name in ("id", "text"):
            _text(row.get(name), name)
        for name in ("source_refs", "source_paths"):
            _strings(row.get(name), name)
        if row["id"] in seen:
            raise ValueError("Duplicate record ID")
        seen.add(row["id"])


def build_corpora(sources, sections):
    """Preserve one full unit per raw row and one full section per MD row.

    This validates source mappings, not the truth or literal support of prepared
    sections. Source admission and MD compilation checks must run upstream.
    """
    if not isinstance(sources, dict) or not isinstance(sections, list):
        raise ValueError("sources must be a dict and sections must be a list")
    raw = []
    for ref, unit in sources.items():
        _text(ref, "source ref")
        if not isinstance(unit, dict):
            raise ValueError("source unit must be a dict")
        for key in ("text", "topic", "path"):
            _text(unit.get(key), "source " + key)
        raw.append({
            **copy.deepcopy(unit), "id": "raw:" + ref,
            "title": unit["topic"], "source_refs": [ref],
            "source_paths": [unit["path"]],
        })
    md = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError("section must be a dict")
        row = copy.deepcopy(section)
        row.setdefault("id", "md:" + str(index))
        _records([row])
        refs = row["source_refs"]
        if any(ref not in sources for ref in refs):
            raise ValueError("Section references an unknown source")
        if set(row["source_paths"]) != {sources[ref]["path"] for ref in refs}:
            raise ValueError("Section paths differ from referenced source paths")
        md.append(row)
    _records(raw)
    _records(md)
    return {"raw": raw, "md": md}


def _limits(top_k, char_budget):
    for name, value in (("top_k", top_k), ("char_budget", char_budget)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(name + " must be a nonnegative integer")


def _vector(values, dimension=None):
    try:
        values = list(values)
    except TypeError as exc:
        raise ValueError("Vector must be a sequence") from exc
    if not values or (dimension is not None and len(values) != dimension):
        raise ValueError("Vector dimension mismatch")
    if any(isinstance(v, bool) or not isinstance(v, Real)
           or not math.isfinite(v) for v in values):
        raise ValueError("Vector values must be finite numbers")
    norm = math.hypot(*(float(v) for v in values))
    if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=.005):
        raise ValueError("Vector must be normalized")
    return [float(v) for v in values]


def _select(ranked, top_k, char_budget, diagnostics):
    selected, seen, used = [], set(), 0
    for row in ranked:
        if len(selected) == top_k:
            break
        text = row["text"]
        if text in seen:
            if diagnostics is not None:
                diagnostics.setdefault("duplicate_text_ids", []).append(row["id"])
            continue
        if len(text) > char_budget or used + len(text) > char_budget:
            if diagnostics is not None:
                key = "oversized_ids" if len(text) > char_budget else "budget_skipped_ids"
                diagnostics.setdefault(key, []).append(row["id"])
            continue
        selected.append(copy.deepcopy(row))
        seen.add(text)
        used += len(text)
    if diagnostics is not None:
        diagnostics.update(selected_count=len(selected), selected_chars=used)
    return selected


def _query_controls(query_vector, top_k, threshold, char_budget, diagnostics,
                    dimension=None):
    _limits(top_k, char_budget)
    if isinstance(threshold, bool) or not isinstance(threshold, Real) or not (
        math.isfinite(threshold) and -1 <= threshold <= 1
    ):
        raise ValueError("threshold must be finite and between -1 and 1")
    if diagnostics is not None:
        diagnostics.clear()
    return _vector(query_vector, dimension)


def _document_vectors(vectors, count, dimension=None):
    try:
        vectors = list(vectors)
    except TypeError as exc:
        raise ValueError("vectors must be a sequence") from exc
    if len(vectors) != count:
        raise ValueError("Record/vector count mismatch")
    checked = []
    for vector in vectors:
        checked.append(_vector(vector, dimension))
        if dimension is None:
            dimension = len(checked[-1])
    return checked


def _valid_refs(valid_refs):
    if not isinstance(valid_refs, (set, frozenset, list, tuple)):
        raise ValueError("valid_refs must be a collection of source refs")
    for ref in valid_refs:
        _text(ref, "valid ref")
    return set(valid_refs)


def _rank(records, vectors, query, valid, top_k, threshold, char_budget,
          diagnostics, allowed_ids=None):
    ranked = []
    for row, vector in zip(records, vectors):
        if allowed_ids is not None and row["id"] not in allowed_ids:
            continue
        if not set(row["source_refs"]) <= valid:
            if diagnostics is not None:
                diagnostics.setdefault("invalid_ref_ids", []).append(row["id"])
            continue
        score = math.fsum(a * b for a, b in zip(vector, query))
        if score < threshold:
            if diagnostics is not None:
                diagnostics.setdefault("below_threshold_ids", []).append(row["id"])
            continue
        ranked.append({**row, "score": score})
    ranked.sort(key=lambda row: (-row["score"], row["id"]))
    return _select(ranked, top_k, char_budget, diagnostics)


def rank_hits(records, vectors, query_vector, valid_refs, top_k=5,
              threshold=.68, char_budget=8000, *, diagnostics=None):
    """Rank full visible rows by cosine descending, then string ID ascending.

    ``vectors`` align positionally with ``records``. ``diagnostics`` optionally
    receives IDs/counts only. Text deduplication is exact; the shared budget is
    Python character count, matching the experiment's existing 8000-char rule.
    """
    _records(records)
    query = _query_controls(query_vector, top_k, threshold, char_budget,
                            diagnostics)
    checked = _document_vectors(vectors, len(records), len(query))
    valid = _valid_refs(valid_refs)
    return _rank(records, checked, query, valid, top_k, threshold, char_budget,
                 diagnostics)


class PreparedIndex:
    """Own a detached snapshot whose document vectors are validated once.

    Source visibility remains request-specific: every reference of a section
    must still be in the current ``valid_refs``, even for allowed record IDs.
    """

    def __init__(self, records, vectors):
        records = copy.deepcopy(records)
        _records(records)
        checked = _document_vectors(vectors, len(records))
        self.__records = tuple(records)
        self.__vectors = tuple(tuple(vector) for vector in checked)
        self.__dimension = len(checked[0]) if checked else None
        self.__ids = frozenset(row["id"] for row in records)

    def rank(self, query_vector, valid_refs, top_k=5, threshold=.68,
             char_budget=8000, *, diagnostics=None, allowed_ids=None):
        """Apply the same scoring and budget rules as ``rank_hits``.

        ``allowed_ids`` optionally limits scoring to known index IDs. It never
        grants source visibility or returns references to the stored records.
        """
        query = _query_controls(query_vector, top_k, threshold, char_budget,
                                diagnostics, self.__dimension)
        valid = _valid_refs(valid_refs)
        if allowed_ids is not None:
            if not isinstance(allowed_ids, (set, frozenset, list, tuple)):
                raise ValueError("allowed_ids must be a collection of record IDs")
            for record_id in allowed_ids:
                _text(record_id, "allowed ID")
            allowed_ids = set(allowed_ids)
            if not allowed_ids <= self.__ids:
                raise ValueError("allowed_ids contains an unknown record ID")
        return _rank(self.__records, self.__vectors, query, valid, top_k,
                     threshold, char_budget, diagnostics, allowed_ids)


def merge_ranks(ranklists, top_k=5, char_budget=8000, *, diagnostics=None):
    """Fuse same-corpus query ranks with RRF k=60; never mix cosine scores.

    Lists must contain hits already gated by ``rank_hits`` for the same request.
    One row contributes once per query. ``score`` remains the first hit's cosine;
    ``rrf_score`` alone determines fusion order, followed by the stable ID tie.
    """
    _limits(top_k, char_budget)
    if diagnostics is not None:
        diagnostics.clear()
    merged = {}
    for rows in ranklists:
        _records(rows)
        for rank, row in enumerate(rows, start=1):
            key = row["id"]
            if key not in merged:
                merged[key] = {**copy.deepcopy(row), "rrf_score": 0.0}
            elif any(merged[key][field] != row[field] for field in (
                "text", "source_refs", "source_paths",
            )):
                raise ValueError("Same record ID has inconsistent source/text")
            merged[key]["rrf_score"] += 1.0 / (60 + rank)
    ranked = sorted(merged.values(), key=lambda row: (-row["rrf_score"], row["id"]))
    return _select(ranked, top_k, char_budget, diagnostics)
