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


def test_merge_search_results_boosts_chunks_hit_by_multiple_queries():
    # 「改寫句」與「原句」都命中的片段，即使各自名次不是第一，也要贏過只被一條查詢命中的第一名
    merged = merge_search_results(
        [
            (
                "改寫句",
                [
                    {"chunk_id": "only-ai", "text": "a", "_distance": 0.10},
                    {"chunk_id": "both", "text": "b", "_distance": 0.20},
                ],
            ),
            (
                "原句",
                [
                    {"chunk_id": "only-user", "text": "c", "_distance": 0.05},
                    {"chunk_id": "both", "text": "b", "_distance": 0.30},
                ],
            ),
        ],
        limit=5,
    )

    # 兩個單命中片段的 RRF 分數相同，改用各自名次內的距離決勝
    assert [record["chunk_id"] for record in merged] == ["both", "only-user", "only-ai"]
    assert merged[0]["matched_queries"] == ["改寫句", "原句"]
    # 保留的是名次較好的那份，距離值仍有意義
    assert merged[0]["_distance"] == 0.2
    assert merged[0]["_rrf_score"] > merged[1]["_rrf_score"]


def test_merge_search_results_does_not_compare_distances_across_queries():
    # 第二條查詢的距離整體偏大，但名次才算數：它的第一名不該被第一條查詢的第二名擠掉
    merged = merge_search_results(
        [
            ("q1", [{"chunk_id": "q1-first", "_distance": 0.1}, {"chunk_id": "q1-second", "_distance": 0.2}]),
            ("q2", [{"chunk_id": "q2-first", "_distance": 0.9}]),
        ],
        limit=2,
    )

    assert [record["chunk_id"] for record in merged] == ["q1-first", "q2-first"]


def test_merge_search_results_respects_limit_after_fusion():
    merged = merge_search_results(
        [("q", [{"chunk_id": str(i), "_distance": i / 10} for i in range(8)])],
        limit=5,
    )

    assert len(merged) == 5
