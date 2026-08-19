"""Fixed BGE-M3 query/document compatibility fixtures and tolerances."""

from __future__ import annotations

import math
from typing import Sequence

EXPECTED_BGE_MODEL = "BAAI/bge-m3"
EXPECTED_DENSE_DIMENSION = 1024
COSINE_SIMILARITY_TOLERANCE = 1e-4

# Fixed evaluation corpus for query/document semantic sanity checks
CORPUS_PAIRS = [
    {
        "query": "什麼是 ESG 永續發展？",
        "positive_doc": "ESG 代表環境保護（E）、社會責任（S）與公司治理（G），是評估企業永續經營的重要指標。",
        "negative_doc": "深度學習模型透過反向傳播演算法更新權重，以最小化損失函數。",
        "min_positive_similarity": 0.55,
        "max_negative_similarity": 0.35,
    },
    {
        "query": "太陽能光電發電原理",
        "positive_doc": "太陽能電池利用光生伏特效應，將太陽光輻射能直接轉換為電能。",
        "negative_doc": "古典音樂中巴哈的賦格曲展示了精緻的對位法與結構對稱性。",
        "min_positive_similarity": 0.55,
        "max_negative_similarity": 0.35,
    },
]


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    if len(vec_a) != len(vec_b):
        raise ValueError(f"Dimension mismatch: {len(vec_a)} vs {len(vec_b)}")
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def validate_vector_contract(vectors: list[list[float]], expected_count: int) -> None:
    """Assert vectors comply with the expected dimension and count."""
    assert len(vectors) == expected_count, f"Expected {expected_count} vectors, got {len(vectors)}"
    for idx, vec in enumerate(vectors):
        assert isinstance(vec, list), f"Vector {idx} is not a list"
        assert len(vec) == EXPECTED_DENSE_DIMENSION, (
            f"Vector {idx} dimension {len(vec)} != expected {EXPECTED_DENSE_DIMENSION}"
        )
        assert all(isinstance(val, (int, float)) for val in vec), f"Vector {idx} contains non-float"
