"""Real BGE-M3 live HTTP gateway inference parity and cosine ranking tests."""

from __future__ import annotations

import math
import os
import httpx
import pytest

try:
    from brain.embedding.tests.fixtures.embedding_fixtures import (
        CORPUS_PAIRS,
        EXPECTED_DENSE_DIMENSION,
        cosine_similarity,
        validate_vector_contract,
    )
except ModuleNotFoundError:
    from tests.fixtures.embedding_fixtures import (
        CORPUS_PAIRS,
        EXPECTED_DENSE_DIMENSION,
        cosine_similarity,
        validate_vector_contract,
    )


async def _fetch_gateway_vectors(
    texts: list[str],
    input_type: str,
) -> list[list[float]]:
    """Obtain vectors strictly via the standalone embedding HTTP service without loading in-process weights."""
    candidate_urls = [
        os.getenv("EMBEDDING_SERVICE_URL", "http://embedding:8009").rstrip("/"),
        "http://127.0.0.1:8009",
        "http://localhost:8009",
        "http://127.0.0.1:8786/api/embedding",
    ]
    token = os.getenv("EMBEDDING_BEARER_TOKEN") or os.getenv("GATEWAY_INTERNAL_TOKEN") or ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    errors = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for base_url in candidate_urls:
            try:
                resp = await client.post(
                    f"{base_url}/embed",
                    json={"texts": texts, "input_type": input_type},
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["vectors"]
                errors.append(f"{base_url}: HTTP {resp.status_code}")
            except Exception as exc:
                errors.append(f"{base_url}: {exc}")

    pytest.skip(
        f"Skipping live BGE parity test: standalone embedding HTTP service not reachable ({'; '.join(errors)})"
    )


@pytest.mark.asyncio
async def test_bge_gateway_live_inference_parity():
    """Verify live HTTP gateway produces 1024-dim L2-normalized vectors and correct ranking."""
    for item in CORPUS_PAIRS:
        query_text = item["query"]
        pos_text = item["positive_doc"]
        neg_text = item["negative_doc"]

        q_vec = (await _fetch_gateway_vectors([query_text], input_type="query"))[0]
        pos_vec = (await _fetch_gateway_vectors([pos_text], input_type="document"))[0]
        neg_vec = (await _fetch_gateway_vectors([neg_text], input_type="document"))[0]

        # 1. Dimension and type contract
        validate_vector_contract([q_vec, pos_vec, neg_vec], 3)

        # 2. L2 Normalization check (norm must be ~ 1.0)
        for vec in (q_vec, pos_vec, neg_vec):
            norm = math.sqrt(sum(x * x for x in vec))
            assert abs(norm - 1.0) < 1e-3, f"Vector L2 norm {norm} != 1.0"

        # 3. Cosine similarity and ranking parity
        pos_sim = cosine_similarity(q_vec, pos_vec)
        neg_sim = cosine_similarity(q_vec, neg_vec)

        assert pos_sim >= item["min_positive_similarity"], (
            f"Query {query_text!r}: pos similarity {pos_sim:.4f} < {item['min_positive_similarity']}"
        )
        assert neg_sim <= item["max_negative_similarity"], (
            f"Query {query_text!r}: neg similarity {neg_sim:.4f} > {item['max_negative_similarity']}"
        )
        assert pos_sim > neg_sim, f"Ranking inversion for query {query_text!r}"
