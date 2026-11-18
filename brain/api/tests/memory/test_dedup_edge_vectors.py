"""Near-duplicate removal keeps the old pairwise behaviour for odd vectors."""

from __future__ import annotations

import math

from memory.fusion import deduplicate


def test_a_nan_vector_does_not_stop_later_duplicates_being_removed():
    records = [
        {"id": "nan", "vector": [math.nan, 1.0]},
        {"id": "a", "vector": [1.0, 0.0]},
        {"id": "a-again", "vector": [1.0, 0.0]},
    ]

    assert [r["id"] for r in deduplicate(records, key_fn=lambda r: r["id"])] == ["nan", "a"]


def test_an_unreadable_vector_is_kept_without_raising():
    records = [
        {"id": "bad", "vector": ["not", "numbers"]},
        {"id": "a", "vector": [1.0, 0.0]},
    ]

    assert [r["id"] for r in deduplicate(records, key_fn=lambda r: r["id"])] == ["bad", "a"]
