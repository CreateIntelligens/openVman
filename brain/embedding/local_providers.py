"""In-process GPU embedding provider: EmbeddingGemma 2."""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Sequence

from identity import EmbeddingSpec, make_canonical_identity

logger = logging.getLogger("embedding_gateway.registry")
_RELEASE_LOG_THRESHOLD_BYTES = 64 * 2**20
# 排隊中的請求合成一批算：短查詢 1 句 91 ms、16 句 94 ms、32 句 99 ms（RTX 16GB 實測），
# 時間幾乎都是固定開銷。上限讓一批不會大到拖慢排在後面的人；前向批次大小另由
# batch_size 控制，VRAM 峰值不因合批變大。
_MERGE_MAX_TEXTS = 64
_MERGE_MAX_CHARS = 16_000
# 全是短句時一次前向放這麼多句；長文件照 batch_size，VRAM 才有上限。
_SHORT_TEXT_CHARS = 256
_SHORT_BATCH_SIZE = 64
# 查詢是使用者在等的（聊天路徑），文件多半是背景建索引：查詢先算。連續這麼多批查詢後
# 還有文件在等，就先算一批文件，免得索引在尖峰時一直排不到。
_QUERY_TYPES = frozenset({"query", "search_query"})
_QUERY_BATCHES_BEFORE_DOCUMENTS = 4


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


def _settle(job: "_Job", vectors: list[list[float]] | None = None, *, exc: BaseException | None = None) -> None:
    # 呼叫端斷線時 future 已被取消，結果就丟掉。
    if job.future.done():
        return
    if exc is not None:
        job.future.set_exception(exc)
    else:
        job.future.set_result(vectors)


@dataclass
class _Job:
    inputs: list[str]
    future: asyncio.Future = field(repr=False)


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
        self.max_concurrency = max(1, max_concurrency)
        self._queries: deque[_Job] = deque()
        self._documents: deque[_Job] = deque()
        self._query_streak = 0
        self._wakeup: asyncio.Event | None = None
        self._workers: list[asyncio.Task] = []
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
        await self._get_or_load_model()
        self._start_workers()
        job = _Job(self._formatted(texts, input_type, titles), asyncio.get_running_loop().create_future())
        (self._queries if input_type in _QUERY_TYPES else self._documents).append(job)
        self._wakeup.set()
        return _l2_normalize(await job.future)

    def _start_workers(self) -> None:
        if self._wakeup is None:
            self._wakeup = asyncio.Event()
        self._workers = [task for task in self._workers if not task.done()]
        while len(self._workers) < self.max_concurrency:
            self._workers.append(asyncio.create_task(self._work()))

    async def _next_batch(self) -> list[_Job]:
        """Take the oldest job of the lane to serve plus what is queued behind it, up to the size limits."""
        while not (self._queries or self._documents):
            self._wakeup.clear()
            await self._wakeup.wait()
        documents_due = self._documents and (
            not self._queries or self._query_streak >= _QUERY_BATCHES_BEFORE_DOCUMENTS
        )
        lane = self._documents if documents_due else self._queries
        # 只數「有文件在等」時連續先算查詢的批數。
        self._query_streak = self._query_streak + 1 if self._documents and not documents_due else 0
        jobs = [lane.popleft()]
        texts = len(jobs[0].inputs)
        chars = sum(len(text) for text in jobs[0].inputs)
        # 放不下的留給下一批，順序不變。
        while lane:
            more = sum(len(text) for text in lane[0].inputs)
            if texts + len(lane[0].inputs) > _MERGE_MAX_TEXTS or chars + more > _MERGE_MAX_CHARS:
                break
            job = lane.popleft()
            jobs.append(job)
            texts += len(job.inputs)
            chars += more
        return [job for job in jobs if not job.future.done()]

    async def _work(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            jobs = await self._next_batch()
            if not jobs:
                continue
            inputs = [text for job in jobs for text in job.inputs]
            try:
                vectors = await self._encode_with_retry(loop, inputs)
            except Exception as exc:
                if len(jobs) == 1:
                    _settle(jobs[0], exc=exc)
                    continue
                # 合批失敗時逐一重算，只讓出問題的那個請求失敗，不連累同批的其他人。
                for job in jobs:
                    try:
                        _settle(job, await self._encode_with_retry(loop, job.inputs))
                    except Exception as single_exc:
                        _settle(job, exc=single_exc)
                continue
            offset = 0
            for job in jobs:
                _settle(job, vectors[offset:offset + len(job.inputs)])
                offset += len(job.inputs)

    async def _encode_with_retry(self, loop: asyncio.AbstractEventLoop, inputs: list[str]) -> list[list[float]]:
        model = self._model
        short = max(len(text) for text in inputs) <= _SHORT_TEXT_CHARS
        batch_size = max(self.batch_size, _SHORT_BATCH_SIZE) if short else self.batch_size

        def _do_encode(size: int) -> list[list[float]]:
            vectors = model.encode(
                inputs,
                batch_size=size,
                convert_to_numpy=True,
                normalize_embeddings=False,
                show_progress_bar=False,
            )
            return vectors.astype("float32").tolist()

        try:
            try:
                return await loop.run_in_executor(None, _do_encode, batch_size)
            except Exception as exc:
                if not (_is_cuda_oom(exc) and len(inputs) > 1):
                    raise
                logger.warning("EmbeddingGemma hit CUDA OOM (texts=%d), retrying with batch_size=1", len(inputs))
                await loop.run_in_executor(None, _release_cuda_cache, self.device, 0)
                return await loop.run_in_executor(None, _do_encode, 1)
        finally:
            await loop.run_in_executor(None, _release_cuda_cache, self.device, len(inputs))

    async def shutdown(self) -> None:
        for task in self._workers:
            task.cancel()
        self._workers = []
        for job in (*self._queries, *self._documents):
            _settle(job, exc=RuntimeError("embedding provider shut down"))
        self._queries.clear()
        self._documents.clear()
        self._wakeup = None
        async with self._init_lock:
            self._model = None
            self._warmup_complete = False
        logger.info("EmbeddingGemma local provider shut down cleanly.")
