"""Vector thresholds: one cosine profile per embedding version."""

from __future__ import annotations

import pytest

from config import BrainSettings
from memory.thresholds import distance_for, similarity_for, thresholds_for


def test_distance_and_similarity_convert_both_ways():
    # LanceDB 的 L2 平方距離：距離 1.0 就是相似度 0.5。
    assert distance_for(0.5) == pytest.approx(1.0)
    assert similarity_for(1.1) == pytest.approx(0.45)
    assert similarity_for(distance_for(0.976)) == pytest.approx(0.976)


def test_profile_follows_the_version_of_an_identity():
    gemma = thresholds_for("gemma:google/embeddinggemma-2:768:float32:l2:query:r")
    assert gemma.retrieval == 0.68
    assert thresholds_for("gemma") == gemma
    # 沒有專屬設定的版本一律沿用 gemma 的值。
    assert thresholds_for("other:m:2:float32:l2:query:r") == gemma


def test_overrides_are_per_version_and_validated():
    overrides = '{"gemma": {"retrieval": 0.7}}'
    assert thresholds_for("gemma", overrides).retrieval == 0.7
    assert thresholds_for("other", overrides).retrieval == 0.68
    with pytest.raises(ValueError, match="不認得"):
        thresholds_for("gemma", '{"gemma": {"cutoff": 0.7}}')
    with pytest.raises(ValueError, match="0 到 1"):
        thresholds_for("gemma", '{"gemma": {"retrieval": 1.2}}')


def test_settings_pick_thresholds_for_the_queried_identity():
    cfg = BrainSettings(embedding_thresholds='{"gemma": {"retrieval": 0.7}}')
    assert cfg.similarity_thresholds().retrieval == 0.7
    query_identity = cfg.resolved_embedding_query_identities[0]
    assert query_identity.startswith("gemma:")
    assert cfg.similarity_thresholds(query_identity).retrieval == 0.7
