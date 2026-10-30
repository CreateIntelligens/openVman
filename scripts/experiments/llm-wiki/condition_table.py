"""Offline exact lookup over manually approved, fully conditioned facts.

Quotes establish only literal value support. This module cannot establish that
the quote supports the assigned entity, attribute, conditions, unit or currency;
``approved`` records the caller's review decision, not an automatic scope check.
It performs no fuzzy matching, unit conversion, interpolation or inference from
independent maxima. Missing dimensions in a source never act as wildcards.
"""

import copy
import re


_REQUIRED = frozenset({
    "id", "entity", "attribute", "conditions", "value", "unit", "source",
})
_SOURCE_FIELDS = frozenset({"ref", "quote", "sha256"})
_HASH = re.compile(r"[0-9a-fA-F]{64}")
_SUPPORT = "Literal value support only; entity/condition scope is not automatically verified."


def _nonempty_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be a nonempty string")


def _conditions(value):
    if not isinstance(value, dict):
        raise ValueError("conditions must be a dict of strings")
    for key, item in value.items():
        _nonempty_string(key, "condition name")
        _nonempty_string(item, "condition value")


class Table:
    """Hold a detached snapshot of validated rows; lookups never mutate it.

    Status precedence is unknown, clarify, conflict, review_required, answer.
    Every response preserves matching rows, including their original conditions
    and source objects. Only ``answer`` exposes a top-level value and unit.
    """

    def __init__(self, records):
        if not isinstance(records, list):
            raise ValueError("records must be a list")
        checked, seen = [], set()
        for record in records:
            if not isinstance(record, dict) or not (
                _REQUIRED <= record.keys() <= _REQUIRED | {"approved"}
            ):
                raise ValueError("record fields do not match the contract")
            for name in ("id", "entity", "attribute", "value"):
                _nonempty_string(record[name], name)
            if record["id"] in seen:
                raise ValueError("Duplicate record ID")
            seen.add(record["id"])
            _conditions(record["conditions"])
            if not isinstance(record["unit"], str):
                raise ValueError("unit must be a string")
            if not isinstance(record.get("approved", False), bool):
                raise ValueError("approved must be a bool")
            source = record["source"]
            if not isinstance(source, dict) or source.keys() != _SOURCE_FIELDS:
                raise ValueError("source fields do not match the contract")
            for name in ("ref", "quote", "sha256"):
                _nonempty_string(source[name], "source " + name)
            if not _HASH.fullmatch(source["sha256"]):
                raise ValueError("source sha256 must be 64 hexadecimal characters")
            if record["value"] not in source["quote"]:
                raise ValueError("value has no literal support in source quote")
            checked.append(copy.deepcopy({**record, "approved": record.get("approved", False)}))
        self._records = checked

    def lookup(self, entity, attribute, conditions):
        """Return exact evidence, or the reason an answer cannot be supplied."""
        _nonempty_string(entity, "entity")
        _nonempty_string(attribute, "attribute")
        _conditions(conditions)
        matches = [
            row for row in self._records
            if row["entity"] == entity and row["attribute"] == attribute
            and all(row["conditions"].get(key) == value
                    for key, value in conditions.items())
        ]
        result = {
            "status": "unknown",
            "entity": entity,
            "attribute": attribute,
            "conditions": copy.deepcopy(conditions),
            "matches": copy.deepcopy(matches),
            "support": _SUPPORT,
        }
        if not matches:
            return result
        missing = sorted({key for row in matches for key in row["conditions"]} - conditions.keys())
        if missing:
            result.update(status="clarify", missing=missing)
            return result
        values = {(row["value"], row["unit"]) for row in matches}
        if len(values) > 1:
            result["status"] = "conflict"
        elif any(not row["approved"] for row in matches):
            result["status"] = "review_required"
        else:
            value, unit = next(iter(values))
            result.update(status="answer", value=value, unit=unit)
        return result
