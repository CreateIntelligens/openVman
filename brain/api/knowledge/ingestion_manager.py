"""知識庫自動 Ingestion 管理器。"""

from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import List, Optional

from .workspace import get_workspace_root, ensure_workspace_scaffold
from .markitdown_service import get_markitdown_service
from .chunker import HeaderBasedChunker
from infra.db import get_knowledge_table, encode_text, ensure_fts_index

logger = logging.getLogger(__name__)


class IngestionManager:
    """管理從原始檔案到向量資料庫的 Ingestion 流程。"""

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.root = get_workspace_root(project_id)
        self.raw_dir = self.root / "raw"
        self.knowledge_dir = self.root / "knowledge"
        self.chunker = HeaderBasedChunker()
        self.md_service = get_markitdown_service()

    def sync_all(self):
        """掃描 raw/ 目錄並同步所有尚未索引的檔案。"""
        ensure_workspace_scaffold(self.project_id)
        
        logger.info(f"Starting bulk ingestion sync for project: {self.project_id}")
        
        for file_path in self.raw_dir.glob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                self.ingest_file(file_path)
        
        # 同步結束後更新 FTS 索引
        ensure_fts_index("knowledge", self.project_id)
        logger.info("Ingestion sync completed.")

    def ingest_file(self, file_path: Path) -> bool:
        """處理單一檔案的 Ingestion：轉換 -> 切分 -> 索引。"""
        # 1. 轉換為 Markdown
        content = self.md_service.convert(file_path)
        if not content:
            return False

        # 2. 儲存轉換後的 Markdown (維護工作區實體檔案)
        md_path = self.knowledge_dir / f"{file_path.name}.md"
        md_path.write_text(content, encoding="utf-8")

        # 3. 切分
        source_meta = {
            "source_file": file_path.name,
            "type": "knowledge_ingestion"
        }
        chunks = self.chunker.split(content, source_metadata=source_meta)

        # 4. 索引到 LanceDB
        records = []
        for chunk in chunks:
            records.append({
                "text": chunk.text,
                "vector": encode_text(chunk.text),
                "source": "ingestion",
                "metadata": json.dumps(chunk.metadata, ensure_ascii=False)
            })
        
        if records:
            table = get_knowledge_table(self.project_id)
            # 這裡簡單採用 append 模式，實務上可根據 source_file 進行重複過濾
            table.add(records)
            logger.info(f"Indexed {len(records)} chunks from {file_path.name}")
            return True
        
        return False


def run_ingestion(project_id: str = "default"):
    """方便外部調用的入口函數。"""
    manager = IngestionManager(project_id)
    manager.sync_all()
