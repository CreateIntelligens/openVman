from tools.search_helpers import merge_search_results


def test_merge_search_results_ranks_hybrid_score_before_distance_fallback():
    merged = merge_search_results(
        [
            (
                "PRP",
                [
                    {"chunk_id": "vector", "text": "vector only", "_distance": 0.2},
                    {"chunk_id": "exact", "text": "PRP exact hit", "_score": 1.0},
                ],
            )
        ],
        limit=2,
    )

    assert [record["chunk_id"] for record in merged] == ["exact", "vector"]
    assert "_distance" not in merged[0]
    assert merged[0]["matched_queries"] == ["PRP"]
