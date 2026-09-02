"""Standalone dense embedding service and provider gateway for BGE-M3 and compatible models."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hmac
import logging
import os
import time
from typing import Any, AsyncIterator, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from identity import EmbeddingSpec
from registry import (
    BgeLocalProvider,
    GeminiApiProvider,
    OpenAiApiProvider,
    ProviderRegistry,
    VoyageApiProvider,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("embedding_service")
for _noisy_logger in ("httpx", "httpcore"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

_ACCESS_LOG_SILENT_PATHS = frozenset({"/health", "/health/ready"})


class _SilentHealthAccessFilter(logging.Filter):
    """Drop uvicorn access log lines for liveness/readiness polling."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn access log: args = (client, method, path, http_version, status)
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        path = str(args[2]).split("?")[0]
        return not (args[4] == 200 and path in _ACCESS_LOG_SILENT_PATHS)


logging.getLogger("uvicorn.access").addFilter(_SilentHealthAccessFilter())

# --- Service Environment Configuration ---
BEARER_TOKEN = (os.getenv("EMBEDDING_BEARER_TOKEN") or os.getenv("GATEWAY_INTERNAL_TOKEN") or "").strip()
SERVICE_REVISION = "1.0.0"

# Local BGE Configuration
DEFAULT_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
MODEL_REVISION = os.getenv(
    "EMBEDDING_MODEL_REVISION",
    "5617a9f61b028005a4858fdac845db406aefb181",
)
DEVICE = os.getenv("EMBEDDING_DEVICE", "cuda")
USE_FP16 = os.getenv("EMBEDDING_USE_FP16", "true").lower() in ("true", "1", "yes")
BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
MAX_LENGTH = int(os.getenv("EMBEDDING_MAX_LENGTH", "8192"))
MAX_CONCURRENCY = int(os.getenv("EMBEDDING_MAX_CONCURRENCY", "1"))
COOLDOWN_SECONDS = float(os.getenv("EMBEDDING_COOLDOWN_SECONDS", "60.0"))

# External Provider Configuration
GEMINI_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = os.getenv("EMBEDDING_GEMINI_MODEL", "gemini-embedding-001")
GEMINI_DIMENSIONS = int(os.getenv("EMBEDDING_GEMINI_DIMENSIONS", "768"))
GEMINI_BASE_URL = os.getenv(
    "EMBEDDING_GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta",
)

OPENAI_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.getenv("EMBEDDING_OPENAI_MODEL", "text-embedding-3-small")
OPENAI_DIMENSIONS = int(os.getenv("EMBEDDING_OPENAI_DIMENSIONS", "1536"))
OPENAI_BASE_URL = os.getenv("EMBEDDING_OPENAI_BASE_URL", "https://api.openai.com/v1")

VOYAGE_KEY = (os.getenv("VOYAGE_API_KEY") or "").strip()
VOYAGE_MODEL = os.getenv("EMBEDDING_VOYAGE_MODEL", "voyage-3-large")
VOYAGE_DIMENSIONS = int(os.getenv("EMBEDDING_VOYAGE_DIMENSIONS", "1024"))
VOYAGE_BASE_URL = os.getenv("EMBEDDING_VOYAGE_BASE_URL", "https://api.voyageai.com/v1")
PROVIDER_TIMEOUT = float(os.getenv("EMBEDDING_PROVIDER_TIMEOUT", "30.0"))

raw_order = os.getenv("EMBEDDING_PROVIDER_FALLBACKS", "bge,gemini,openai,voyage")
FALLBACK_ORDER = [p.strip().lower() for p in raw_order.split(",") if p.strip()]

MAX_REQUEST_TEXTS = 512

# --- Global Registry Lifecycle ---
_registry: ProviderRegistry | None = None


def _get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        reg = ProviderRegistry(cooldown_seconds=COOLDOWN_SECONDS, fallback_order=FALLBACK_ORDER)
        # Register BGE local
        reg.register(
            "bge",
            BgeLocalProvider(
                model_name=DEFAULT_MODEL,
                model_revision=MODEL_REVISION,
                device=DEVICE,
                use_fp16=USE_FP16,
                batch_size=BATCH_SIZE,
                max_length=MAX_LENGTH,
                max_concurrency=MAX_CONCURRENCY,
            ),
        )
        # Register Gemini
        reg.register(
            "gemini",
            GeminiApiProvider(
                api_key=GEMINI_KEY,
                model=GEMINI_MODEL,
                dimensions=GEMINI_DIMENSIONS,
                base_url=GEMINI_BASE_URL,
                timeout=PROVIDER_TIMEOUT,
            ),
        )
        # Register OpenAI
        reg.register(
            "openai",
            OpenAiApiProvider(
                api_key=OPENAI_KEY,
                model=OPENAI_MODEL,
                dimensions=OPENAI_DIMENSIONS,
                base_url=OPENAI_BASE_URL,
                timeout=PROVIDER_TIMEOUT,
            ),
        )
        # Register Voyage
        reg.register(
            "voyage",
            VoyageApiProvider(
                api_key=VOYAGE_KEY,
                model=VOYAGE_MODEL,
                dimensions=VOYAGE_DIMENSIONS,
                base_url=VOYAGE_BASE_URL,
                timeout=PROVIDER_TIMEOUT,
            ),
        )
        _registry = reg
    return _registry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting embedding-service gateway (revision %s)", SERVICE_REVISION)
    reg = _get_registry()
    yield
    logger.info("Shutting down embedding-service gateway...")
    await reg.shutdown()
    logger.info("Embedding service stopped cleanly.")


app = FastAPI(
    title="openVman Embedding Gateway",
    version=SERVICE_REVISION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("EMBEDDING_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Authentication Dependency ---
def verify_bearer_token(authorization: str | None = Header(None)) -> None:
    if not BEARER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding service authentication is not configured",
        )
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    parts = authorization.split()
    if (
        len(parts) != 2
        or parts[0].lower() != "bearer"
        or not hmac.compare_digest(parts[1], BEARER_TOKEN)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
        )


# --- Request/Response Schemas ---
class JtaiEmbedRequest(BaseModel):
    texts: list[str] = Field(..., description="List of strings to embed")
    input_type: Literal["document", "query", "symmetric"] = Field(
        "document", description="Embedding input semantics"
    )
    acceptable_identities: list[str] | None = Field(
        None, description="List of canonical identities the caller can accept"
    )
    identity: str | None = Field(
        None, description="Explicitly requested canonical identity (for multi-chunk locking)"
    )


class JtaiEmbedResponse(BaseModel):
    vectors: list[list[float]]
    model: str
    embedding_spec: dict[str, Any]
    attempts: list[dict[str, Any]]


class OpenAIEmbeddingsRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    encoding_format: str | None = "float"
    dimensions: int | None = None
    user: str | None = None


class OpenAIEmbeddingObject(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class OpenAIEmbeddingsResponse(BaseModel):
    object: str = "list"
    data: list[OpenAIEmbeddingObject]
    model: str
    usage: dict[str, int]
    openvman_embedding_spec: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] | None = None


# --- Endpoints ---
@app.get("/health")
async def health_liveness() -> dict[str, str]:
    return {"status": "ok", "service": "embedding-service"}


@app.get("/health/ready")
async def health_readiness(
    _: None = Depends(verify_bearer_token),
) -> dict[str, Any]:
    reg = _get_registry()
    report = await reg.inspect_readiness()

    if report["status"] == "unavailable":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unavailable",
                "error": report.get("detail", "No embedding providers available"),
                "providers": report.get("providers", {}),
            },
        )

    ready_specs = [
        provider["spec"]
        for provider in report.get("providers", {}).values()
        if provider.get("status") == "ready" and provider.get("spec")
    ]
    preferred_spec = ready_specs[0] if ready_specs else {}

    return {
        "status": report["status"],
        "service": "embedding-service",
        "service_revision": SERVICE_REVISION,
        "model": preferred_spec.get("model", ""),
        "dimension": preferred_spec.get("dimensions", 0),
        "normalization": preferred_spec.get("normalization", "l2"),
        "embedding_spec": preferred_spec,
        "available_providers": list(report.get("providers", {}).keys()),
        "providers_status": report.get("providers", {}),
    }


@app.get("/v1/models")
async def list_models(
    _: None = Depends(verify_bearer_token),
) -> dict[str, Any]:
    reg = _get_registry()
    specs = reg.get_available_specs()
    model_data = [
        {
            "id": spec.model,
            "object": "model",
            "created": int(time.time()),
            "owned_by": f"openvman-{spec.provider}",
            "dimensions": spec.dimensions,
            "identity": spec.identity,
            "normalization": spec.normalization,
            "input_semantics": spec.input_semantics,
            "model_revision": spec.model_revision,
        }
        for spec in specs
    ]
    return {"object": "list", "data": model_data}


@app.post("/embed", response_model=JtaiEmbedResponse)
async def jtai_embed(
    payload: JtaiEmbedRequest,
    _: None = Depends(verify_bearer_token),
) -> JtaiEmbedResponse:
    if len(payload.texts) > MAX_REQUEST_TEXTS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch size {len(payload.texts)} exceeds maximum {MAX_REQUEST_TEXTS}",
        )

    reg = _get_registry()

    # Handle empty batch
    if not payload.texts:
        available_specs = reg.get_available_specs(input_semantics=payload.input_type)
        if not available_specs:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No embedding providers available",
            )
        target_spec = available_specs[0]
        if payload.identity:
            matched = [s for s in available_specs if s.identity == payload.identity.strip()]
            if not matched:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Requested identity '{payload.identity}' is not configured or served",
                )
            target_spec = matched[0]

        return JtaiEmbedResponse(
            vectors=[],
            model=target_spec.model,
            embedding_spec=target_spec.to_dict(),
            attempts=[],
        )

    try:
        vectors, spec, attempts = await reg.resolve_and_encode(
            payload.texts,
            input_type=payload.input_type,
            acceptable_identities=payload.acceptable_identities,
            requested_identity=payload.identity,
        )
        return JtaiEmbedResponse(
            vectors=vectors,
            model=spec.model,
            embedding_spec=spec.to_dict(),
            attempts=attempts,
        )
    except Exception as exc:
        logger.error("Embedding request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None


@app.post("/v1/embeddings", response_model=OpenAIEmbeddingsResponse)
async def openai_embeddings(
    payload: OpenAIEmbeddingsRequest,
    _: None = Depends(verify_bearer_token),
) -> OpenAIEmbeddingsResponse:
    texts = [payload.input] if isinstance(payload.input, str) else list(payload.input)
    if len(texts) > MAX_REQUEST_TEXTS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch size {len(texts)} exceeds maximum {MAX_REQUEST_TEXTS}",
        )

    reg = _get_registry()
    available_specs = reg.get_available_specs(input_semantics="document")

    # Match requested model
    requested_model = (payload.model or "").strip()
    requested_identity = None

    if requested_model:
        matched = [
            s for s in available_specs
            if s.model == requested_model or s.identity == requested_model
        ]
        if not matched:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"The model '{requested_model}' does not exist or is not served/configured",
            )
        requested_identity = matched[0].identity

    if not texts:
        spec = matched[0] if requested_model else available_specs[0]
        return OpenAIEmbeddingsResponse(
            object="list",
            data=[],
            model=spec.model,
            usage={"prompt_tokens": 0, "total_tokens": 0},
            openvman_embedding_spec=spec.to_dict(),
            attempts=[],
        )

    try:
        vectors, spec, attempts = await reg.resolve_and_encode(
            texts,
            input_type="document",
            requested_identity=requested_identity,
        )
        total_tokens = sum(len(t.split()) for t in texts)
        data = [
            OpenAIEmbeddingObject(object="embedding", index=idx, embedding=vec)
            for idx, vec in enumerate(vectors)
        ]
        return OpenAIEmbeddingsResponse(
            object="list",
            data=data,
            model=spec.model,
            usage={"prompt_tokens": total_tokens, "total_tokens": total_tokens},
            openvman_embedding_spec=spec.to_dict(),
            attempts=attempts,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("OpenAI embeddings request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
