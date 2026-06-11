"""檢索結果融合工具 — RRF (Reciprocal Rank Fusion)、分數正規化與去重。

純函式模組,不依賴 LanceDB;輸入輸出皆為 record dict list,且不可變
(永不修改傳入的 record)。
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

KeyFn = Callable[[dict[str, Any]], Any]

DEFAULT_RRF_K = 60
DEFAULT_DEDUP_SIMILARITY = 0.95


def _default_key(record: dict[str, Any]) -> Any:
    """Record 身分鍵:優先 id,否則以 text 內容當作身分。"""
    return record.get("id") or record.get("text")


def rrf_fuse(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    k: int = DEFAULT_RRF_K,
    key_fn: KeyFn | None = None,
) -> list[dict[str, Any]]:
    """以 RRF 融合多路檢索結果。

    score(d) = Σ_lists 1 / (k + rank + 1),rank 從 0 起算。
    同一筆 record 出現在多路時分數累加;欄位以先出現的列表為準,
    缺少的欄位從後出現的補上(例如 vector 路的 _distance + FTS 路的 _score)。
    回傳依 _rrf_score 由高到低排序的新 record list。
    """
    resolve_key = key_fn or _default_key
    scores: dict[Any, float] = {}
    merged: dict[Any, dict[str, Any]] = {}

    for results in ranked_lists:
        for rank, record in enumerate(results):
            key = resolve_key(record)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key in merged:
                # 先出現者欄位優先,後出現者只補缺
                merged[key] = {**record, **merged[key]}
            else:
                merged[key] = record

    fused = [{**merged[key], "_rrf_score": score} for key, score in scores.items()]
    return sorted(fused, key=lambda r: r["_rrf_score"], reverse=True)


def min_max_normalize(
    records: list[dict[str, Any]],
    *,
    source_field: str,
    out_field: str = "_score",
    invert: bool = False,
) -> list[dict[str, Any]]:
    """對 source_field 做 min-max 正規化,寫入 out_field ∈ [0, 1]。

    invert=True 用於「越小越好」的欄位(如 _distance),反轉後高分代表更相關。
    全部值相同(或只有一筆)時一律給 1.0。缺少 source_field 的 record
    原樣保留、不寫 out_field。回傳新 record list,不修改輸入。
    """
    values = [float(r[source_field]) for r in records if source_field in r]
    if not values:
        return [dict(r) for r in records]

    lo, hi = min(values), max(values)
    span = hi - lo

    normalized: list[dict[str, Any]] = []
    for record in records:
        if source_field not in record:
            normalized.append(dict(record))
            continue
        if span == 0:
            score = 1.0
        else:
            score = (float(record[source_field]) - lo) / span
            if invert:
                score = 1.0 - score
        normalized.append({**record, out_field: score})
    return normalized


def deduplicate(
    records: list[dict[str, Any]],
    *,
    similarity_threshold: float = DEFAULT_DEDUP_SIMILARITY,
    vector_field: str = "vector",
    key_fn: KeyFn | None = None,
) -> list[dict[str, Any]]:
    """去重:先以身分鍵去 exact 重複,再以 embedding 餘弦相似度去近似重複。

    輸入應已依相關性排序;重複時保留排序較前的一筆。
    沒有 vector 的 record 只做 exact 去重。回傳新 list(record 本身不複製,
    因為僅做篩選不做修改)。
    """
    seen_keys: set[Any] = set()
    kept: list[dict[str, Any]] = []
    kept_vectors: list[Any] = []
    resolve_key = key_fn or _default_key

    for record in records:
        key = resolve_key(record)
        if key is not None and key in seen_keys:
            continue

        vector = record.get(vector_field)
        if vector is not None and _is_near_duplicate(vector, kept_vectors, similarity_threshold):
            continue

        if key is not None:
            seen_keys.add(key)
        if vector is not None:
            kept_vectors.append(vector)
        kept.append(record)

    return kept


def _is_near_duplicate(
    vector: Any,
    kept_vectors: list[Any],
    threshold: float,
) -> bool:
    return any(cosine_similarity(vector, kept) >= threshold for kept in kept_vectors)


def cosine_similarity(vec_a: Any, vec_b: Any) -> float:
    """餘弦相似度;長度不符或零向量回 0.0。"""
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    if a.shape != b.shape or a.size == 0:
        return 0.0
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
