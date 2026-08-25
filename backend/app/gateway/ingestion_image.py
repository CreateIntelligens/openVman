"""Image ingestion — Vision LLM description with OCR fallback."""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path

from openai import AsyncOpenAI

from app.config import get_tts_config
from app.gateway.ingestion import IngestionResult

logger = logging.getLogger("gateway.ingestion_image")

_VISION_PROMPT = (
    "請用繁體中文詳細描述這張圖片的內容，"
    "包括文字、物件、場景、顏色等重要資訊。"
)


def _read_image_base64(file_path: str) -> tuple[str, str]:
    """Read image file and return (base64_data, mime_type)."""
    data = Path(file_path).read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    mime, _ = mimetypes.guess_type(file_path)
    return b64, mime or "image/jpeg"


async def _describe_with_vision(file_path: str, trace_id: str, cfg: Any = None) -> str:
    """Call Vision LLM API for image description."""
    from app.gateway.vlm_client import get_vlm_client, resolve_vlm_route

    route = resolve_vlm_route(cfg)
    client = get_vlm_client(cfg)
    if client is None:
        return ""

    b64_data, mime_type = _read_image_base64(file_path)
    response = await client.chat.completions.create(
        model=route.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{b64_data}",
                        },
                    },
                ],
            }
        ],
        max_tokens=256,
    )
    return response.choices[0].message.content or ""


def _ocr_fallback(file_path: str, trace_id: str) -> str:
    """Fallback: pytesseract OCR (chi_tra + eng)."""
    import pytesseract
    from PIL import Image

    logger.info("ocr_fallback trace_id=%s path=%s", trace_id, file_path)
    img = Image.open(file_path)
    text = pytesseract.image_to_string(img, lang="chi_tra+eng")
    return text.strip()


async def describe(file_path: str, trace_id: str) -> IngestionResult:
    """Describe an image using Vision LLM with OCR fallback.

    Returns IngestionResult with content_type="image_description".
    """
    cfg = get_tts_config()

    # Try Vision LLM first if API key is configured
    if cfg.vision_llm_api_key:
        try:
            content = await _describe_with_vision(file_path, trace_id, cfg)
            logger.info("vision_llm_ok trace_id=%s chars=%d", trace_id, len(content))
            return IngestionResult(content_type="image_description", content=content)
        except Exception as exc:
            logger.warning("vision_llm_failed trace_id=%s err=%s", trace_id, exc)

    # OCR fallback
    try:
        content = _ocr_fallback(file_path, trace_id)
        if content:
            logger.info("ocr_ok trace_id=%s chars=%d", trace_id, len(content))
            return IngestionResult(content_type="image_description", content=content)
    except Exception as exc:
        logger.warning("ocr_failed trace_id=%s err=%s", trace_id, exc)

    # Graceful degradation
    logger.error("image_ingestion_failed trace_id=%s", trace_id)
    return IngestionResult(
        content_type="image_description",
        content="（圖片描述服務暫時無法使用）",
    )
