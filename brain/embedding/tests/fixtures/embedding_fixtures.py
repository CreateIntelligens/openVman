"""Expected EmbeddingGemma vector contract shared by the gateway tests."""

from __future__ import annotations

EXPECTED_MODEL = "google/embeddinggemma-2"
EXPECTED_DENSE_DIMENSION = 768


def validate_vector_contract(vectors: list[list[float]], expected_count: int) -> None:
    """Assert vectors comply with the expected dimension and count."""
    assert len(vectors) == expected_count, f"Expected {expected_count} vectors, got {len(vectors)}"
    for idx, vec in enumerate(vectors):
        assert isinstance(vec, list), f"Vector {idx} is not a list"
        assert len(vec) == EXPECTED_DENSE_DIMENSION, (
            f"Vector {idx} dimension {len(vec)} != expected {EXPECTED_DENSE_DIMENSION}"
        )
        assert all(isinstance(val, (int, float)) for val in vec), f"Vector {idx} contains non-float"
