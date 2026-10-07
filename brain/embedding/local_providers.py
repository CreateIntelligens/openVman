"""In-process GPU embedding provider: EmbeddingGemma 2."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Sequence

from identity import EmbeddingSpec, make_canonical_identity

logger = logging.getLogger("embedding_gateway.registry")
_RELEASE_LOG_THRESHOLD_BYTES = 64 * 2**20


def _l2_normalize(vectors: Sequence[Sequence[float]]) -> list[list[float]]:
    normalized_vectors: list[list[float]] = []
    for vec in vectors:
        norm = math.sqrt(sum(float(x) * float(x) for x in vec))
        if norm > 1e-12:
            normalized_vectors.append([float(x) / norm for x in vec])
        else:
            normalized_vectors.append([float(x) for x in vec])
    return normalized_vectors


def _release_cuda_cache(device: str, text_count: int = 0) -> None:
    if not str(device).startswith("cuda"):
        return
    try:
        import torch

        before = torch.cuda.memory_reserved()
        torch.cuda.empty_cache()
        after = torch.cuda.memory_reserved()
    except Exception:
        logger.debug("CUDA cache release failed", exc_info=True)
        return
    # 只記有實際釋放的大批次；一般查詢每次都記會洗版。留著這筆紀錄才看得出
    # 常駐量是否仍隨時間上漲（例如權重以外還有東西在漏）。
    if before - after >= _RELEASE_LOG_THRESHOLD_BYTES:
        logger.info(
            "CUDA cache released texts=%d reserved_mb=%.0f->%.0f allocated_mb=%.0f",
            text_count, before / 2**20, after / 2**20,
            torch.cuda.memory_allocated() / 2**20,
        )


def _is_cuda_oom(exc: Exception) -> bool:
    return "out of memory" in str(exc).lower() or exc.__class__.__name__ == "OutOfMemoryError"


# EmbeddingGemma 2 是非對稱模型：查詢與文件要加不同的前綴，向量才在同一個空間裡可比。
# 查詢用 question answering 而不是 search result：鶴記 57 句語音辨識打錯字的查詢，
# 純向量前 3 名命中 35 對 32（scripts/experiments/embeddinggemma2/）。
# search_query 給 jtai：它的口語改寫題用 search result 前綴前 5 名命中 80、question answering 75
# （BGE 83），所以兩種查詢語意都提供，文件端共用。
_GEMMA_PREFIXES = {
    "query": "task: question answering | query: ",
    "search_query": "task: search result | query: ",
    "symmetric": "task: sentence similarity | query: ",
}


class GemmaLocalProvider:
    """Lazy-loaded in-process EmbeddingGemma 2 provider (sentence-transformers, bf16)."""

    accepts_titles = True

    def __init__(
        self,
        model_name: str = "google/embeddinggemma-2",
        model_revision: str = "default",
        device: str = "cuda",
        batch_size: int = 16,
        max_length: int = 2048,
        max_concurrency: int = 1,
    ) -> None:
        self.model_name = model_name
        self.model_revision = model_revision
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self._dimensions = 768
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._init_lock = asyncio.Lock()
        self._model: Any = None
        self._warmup_complete = False

    @property
    def is_configured(self) -> bool:
        return True

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        identity = make_canonical_identity(
            provider="gemma",
            model=self.model_name,
            dimensions=self._dimensions,
            dtype="float32",
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
        )
        return EmbeddingSpec(
            identity=identity,
            provider="gemma",
            model=self.model_name,
            dimensions=self._dimensions,
            dtype="float32",
            normalized=True,
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
            service_revision="1.0.0",
        )

    async def _get_or_load_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._init_lock:
            if self._model is not None:
                return self._model
            loop = asyncio.get_running_loop()

            def _load() -> Any:
                import torch
                from sentence_transformers import SentenceTransformer

                logger.info("Initializing EmbeddingGemma '%s' on %s (bf16)...", self.model_name, self.device)
                revision = None if self.model_revision in {"", "default"} else self.model_revision
                # 官方說明 fp16 會出 NaN，只能用 bf16 或 fp32。
                dtype = torch.bfloat16 if str(self.device).startswith("cuda") else torch.float32
                model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                    revision=revision,
                    model_kwargs={"torch_dtype": dtype},
                )
                model.max_seq_length = self.max_length
                return model

            self._model = await loop.run_in_executor(None, _load)
            logger.info("EmbeddingGemma '%s' loaded successfully.", self.model_name)
            return self._model

    async def is_ready(self) -> bool:
        try:
            await self._get_or_load_model()
            return True
        except Exception:
            return False

    async def warmup(self) -> None:
        if self._warmup_complete:
            return
        await self.encode(["warmup probe"], input_type="query")
        self._warmup_complete = True

    def _formatted(self, texts: list[str], input_type: str, titles: list[str] | None) -> list[str]:
        prefix = _GEMMA_PREFIXES.get(input_type)
        if prefix is not None:
            return [prefix + text for text in texts]
        names = titles if titles and len(titles) == len(texts) else [""] * len(texts)
        return [f"title: {(name or '').strip() or 'none'} | text: {text}" for name, text in zip(names, texts)]

    async def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
        titles: list[str] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        model = await self._get_or_load_model()
        loop = asyncio.get_running_loop()
        inputs = self._formatted(texts, input_type, titles)

        def _do_encode(batch_size: int) -> list[list[float]]:
            vectors = model.encode(
                inputs,
                batch_size=batch_size,
                convert_to_numpy=True,
                normalize_embeddings=False,
                show_progress_bar=False,
            )
            return vectors.astype("float32").tolist()

        async with self._semaphore:
            try:
                try:
                    vectors = await loop.run_in_executor(None, _do_encode, self.batch_size)
                except Exception as exc:
                    if not (_is_cuda_oom(exc) and len(texts) > 1):
                        raise
                    logger.warning("EmbeddingGemma hit CUDA OOM (texts=%d), retrying with batch_size=1", len(texts))
                    await loop.run_in_executor(None, _release_cuda_cache, self.device, 0)
                    vectors = await loop.run_in_executor(None, _do_encode, 1)
            finally:
                await loop.run_in_executor(None, _release_cuda_cache, self.device, len(texts))
        return _l2_normalize(vectors)

    async def shutdown(self) -> None:
        async with self._init_lock:
            self._model = None
            self._warmup_complete = False
        logger.info("EmbeddingGemma local provider shut down cleanly.")
