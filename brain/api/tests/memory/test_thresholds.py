"""Vector thresholds: one cosine profile per embedding version."""

from __future__ import annotations

import pytest

from config import BrainSettings
from memory.thresholds import distance_for, similarity_for, thresholds_for


def test_distance_and_similarity_convert_both_ways():
    # LanceDB 的 L2 平方距離：原本 BGE 的檢索門檻 1.0 就是相似度 0.5。
    assert distance_for(0.5) == pytest.approx(1.0)
    assert similarity_for(1.1) == pytest.approx(0.45)
    assert similarity_for(distance_for(0.976)) == pytest.approx(0.976)


def test_profile_follows_the_version_of_an_identity():
    gemma = thresholds_for("gemma:google/embeddinggemma-2:768:float32:l2:query:r")
    bge = thresholds_for("bge:BAAI/bge-m3:1024:float32:l2:query:r")
    assert gemma.retrieval == 0.68 and bge.retrieval == 0.50
    # 沒校正過的雲端模型沿用 BGE 的值。
    assert thresholds_for("openai") == bge


def test_overrides_are_per_version_and_validated():
    overrides = '{"gemma": {"retrieval": 0.68}}'
    assert thresholds_for("gemma", overrides).retrieval == 0.68
    assert thresholds_for("bge", overrides).retrieval == 0.50
    with pytest.raises(ValueError, match="不認得"):
        thresholds_for("gemma", '{"gemma": {"cutoff": 0.7}}')
    with pytest.raises(ValueError, match="0 到 1"):
        thresholds_for("gemma", '{"gemma": {"retrieval": 1.2}}')


def test_settings_pick_thresholds_for_the_queried_version_not_only_the_active_one():
    cfg = BrainSettings(embedding_active_version="gemma")
    assert cfg.similarity_thresholds().retrieval == 0.68
    # 新版本還沒建索引、查詢退回 BGE 的表時，門檻要用 BGE 的。
    bge_identity = cfg.resolved_embedding_query_identities[1]
    assert bge_identity.startswith("bge:")
    assert cfg.similarity_thresholds(bge_identity).retrieval == 0.50
