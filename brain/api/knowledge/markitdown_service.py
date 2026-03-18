"""Microsoft MarkItDown 整合服務。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from markitdown import MarkItDown

logger = logging.getLogger(__name__)


class MarkItDownService:
    """使用 MarkItDown 將多種格式轉換為 Markdown 的服務。"""

    def __init__(self):
        self._md = MarkItDown()

    def convert(self, file_path: Path | str) -> Optional[str]:
        """將指定路徑的檔案轉換為 Markdown 字串。

        支援格式：PDF, DOCX, XLSX, PPTX, HTML, RSS, ATOM, 
        甚至部分音頻 (若環境支援) 與圖像。
        """
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {path}")
            return None

        try:
            logger.info(f"Converting file to Markdown: {path}")
            result = self._md.convert(str(path))
            return result.text_content
        except Exception as e:
            logger.exception(f"Failed to convert {path} to Markdown: {e}")
            return None


# 全域實例
_service: Optional[MarkItDownService] = None


def get_markitdown_service() -> MarkItDownService:
    """取得 MarkItDownService 單例。"""
    global _service
    if _service is None:
        _service = MarkItDownService()
    return _service
