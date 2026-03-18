"""知識庫自動 Ingestion 管理器。

職責：將 raw/ 目錄的原始檔案（PDF, DOCX 等）轉換為 Markdown 並存入
knowledge/ 目錄。分塊與向量化統一由 indexer.rebuild_knowledge_index() 處理。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .workspace import ensure_workspace_scaffold
from .markitdown_service import get_markitdown_service
from .indexer import rebuild_knowledge_index

logger = logging.getLogger(__name__)


class IngestionManager:
    """管理從原始檔案到 Markdown 的轉換流程。"""

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.root = ensure_workspace_scaffold(project_id)
        self.raw_dir = self.root / "raw"
        self.knowledge_dir = self.root / "knowledge"
        self.md_service = get_markitdown_service()

    def sync_all(self) -> dict[str, Any]:
        """掃描 raw/ 目錄，轉檔後統一重建索引。"""
        converted = 0
        skipped = 0

        for file_path in sorted(self.raw_dir.glob("*")):
            if not file_path.is_file() or file_path.name.startswith("."):
                continue
            if self._convert_to_markdown(file_path):
                converted += 1
            else:
                skipped += 1

        logger.info(f"Ingestion: converted={converted}, skipped={skipped}")

        # 統一由 indexer 處理分塊 + 向量化 + 索引
        index_result = rebuild_knowledge_index(self.project_id)

        return {
            "converted": converted,
            "skipped": skipped,
            **index_result,
        }

    def _convert_to_markdown(self, file_path: Path) -> bool:
        """將單一檔案轉為 Markdown 存入 knowledge/ 目錄。"""
        md_path = self.knowledge_dir / f"{file_path.name}.md"

        content = self.md_service.convert(file_path)
        if not content:
            logger.warning(f"Failed to convert: {file_path.name}")
            return False

        md_path.write_text(content, encoding="utf-8")
        logger.info(f"Converted: {file_path.name} -> {md_path.name}")
        return True


def run_ingestion(project_id: str = "default") -> dict[str, Any]:
    """方便外部調用的入口函數。"""
    manager = IngestionManager(project_id)
    return manager.sync_all()
