"""Embedding 封裝 — BAAI/bge-m3 Singleton。"""

from threading import Lock

from FlagEmbedding import BGEM3FlagModel

from config import get_settings

_model: BGEM3FlagModel | None = None
_model_lock = Lock()
_encode_lock = Lock()


def get_embedder() -> "Embedder":
    """Singleton 取得 Embedder 實例（首次呼叫時載入模型 ~2.2GB）"""
    global _model
    if _model is not None:
        return Embedder(_model)

    with _model_lock:
        if _model is None:
            _model = _build_model()
    return Embedder(_model)


def _build_model() -> BGEM3FlagModel:
    cfg = get_settings()
    return BGEM3FlagModel(
        cfg.embedding_model,
        use_fp16=cfg.embedding_use_fp16,
        device=cfg.embedding_device,
    )


class Embedder:
    """bge-m3 向量化封裝，回傳 1024 維 dense vectors"""

    def __init__(self, model: BGEM3FlagModel) -> None:
        self._model = model

    def encode(self, texts: list[str]) -> list[list[float]]:
        """批次向量化文字，回傳 list[list[float]]（每筆 1024 維）"""
        with _encode_lock:
            result = self._model.encode(texts)
        dense_vecs = result["dense_vecs"]
        return [vec.tolist() for vec in dense_vecs]


def encode_text(text: str) -> list[float]:
    """單筆文字向量化，避免呼叫端重複取第一筆。"""
    return get_embedder().encode([text])[0]
