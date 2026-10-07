"""Vector thresholds: one cosine-similarity profile per embedding model.

所有向量門檻都用 cosine 相似度寫（0–1，越大越像），不再混用 LanceDB 距離、
cosine 與「1 − 距離」三種寫法。LanceDB 回的是 L2 平方距離；向量都已正規化，
所以距離 = 2 − 2 × 相似度，換算集中在這裡。

不同模型的相似度分布差很多（鶴記同一批段落兩兩相似度中位數：BGE-M3 0.50、
EmbeddingGemma 2 0.74），同一個數字放到另一個模型上意思完全不同，所以門檻
跟著 embedding 版本走，一個版本一組。來源：
- gemma：scripts/experiments/embeddinggemma2/。檢索門檻用鶴記 170 題實測校正；
  去重、合併、切段沒有標準答案，以當時 BGE-M3 的門檻（原設定值）在同一批資料上的分位數換算。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class SimilarityThresholds:
    # 向量檢索：段落跟問題至少這麼像才帶進回答。
    retrieval: float
    # 關鍵字（FTS）也命中的段落用較寬的門檻；不能無條件放行，西語「qué」這種常見字什麼都命中。
    retrieval_fts: float
    # 檢索結果兩段這麼像就只留排前面的。
    dedup: float
    # 長期記憶兩筆這麼像就合併。
    memory_merge: float
    # 夢境整理：新記憶跟既有記憶這麼像就不寫。
    dreaming_dedup: float
    # 無標題 Markdown 依語意切段：相鄰句子低於這個就切開。
    chunk_split: float
    # 長期記憶排序時加的分，讓記憶跟知識庫同分時記憶排前面。
    memory_bonus: float
    # 網路搜尋結果對原句重排：低於絕對下限或低於最佳結果的這個比例就丟掉，兩者取較嚴者。
    web_min_relevance: float
    web_relevance_ratio: float


_PROFILES: dict[str, SimilarityThresholds] = {
    # 檢索門檻在正式檢索路徑（混合檢索、語言排序、去重）上掃過：0.68 時鶴記中英西 36/36、
    # 跨語言 47/48、語音辨識打錯字 30/57（BGE 36、46、25），但「你好」「hola」這類招呼語
    # 會帶進幾段；0.72 才沒有雜訊，命中卻全面低於 BGE。
    "gemma": SimilarityThresholds(
        retrieval=0.68,
        retrieval_fts=0.63,
        dedup=0.976,
        memory_merge=0.965,
        dreaming_dedup=0.976,
        chunk_split=0.813,
        memory_bonus=0.01,
        web_min_relevance=0.44,
        web_relevance_ratio=0.87,
    ),
}
_FALLBACK = "gemma"


def distance_for(similarity: float) -> float:
    """LanceDB L2-squared distance of two unit vectors with this cosine similarity."""
    return 2.0 - 2.0 * similarity


def similarity_for(distance: float) -> float:
    return 1.0 - distance / 2.0


def version_of(version_or_identity: str) -> str:
    """'gemma' from 'gemma' or 'gemma:google/embeddinggemma-2:768:…'."""
    return version_or_identity.strip().lower().split(":", 1)[0]


def thresholds_for(version_or_identity: str, overrides: str = "") -> SimilarityThresholds:
    """Profile for an embedding version, with ``EMBEDDING_THRESHOLDS`` overrides applied.

    ``overrides`` is a JSON object keyed by version, e.g. ``{"gemma": {"retrieval": 0.68}}``.
    """
    version = version_of(version_or_identity)
    profile = _PROFILES.get(version, _PROFILES[_FALLBACK])
    if not overrides.strip():
        return profile
    try:
        parsed = json.loads(overrides)
    except json.JSONDecodeError as exc:
        raise ValueError("EMBEDDING_THRESHOLDS 必須是 JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("EMBEDDING_THRESHOLDS 必須是 JSON object")
    changes = parsed.get(version) or {}
    if not isinstance(changes, dict):
        raise ValueError(f"EMBEDDING_THRESHOLDS.{version} 必須是 JSON object")
    known = {field.name for field in fields(SimilarityThresholds)}
    unknown = set(changes) - known
    if unknown:
        raise ValueError(f"EMBEDDING_THRESHOLDS 不認得：{', '.join(sorted(unknown))}")
    for name, value in changes.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= value <= 1.0:
            raise ValueError(f"EMBEDDING_THRESHOLDS.{version}.{name} 必須是 0 到 1 的相似度")
    return replace(profile, **{name: float(value) for name, value in changes.items()})
