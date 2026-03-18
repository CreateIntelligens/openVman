"""基於 Markdown 標題的語義切分器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class Chunk:
    text: str
    metadata: dict


class HeaderBasedChunker:
    """根據 H1, H2, H3 標題切分 Markdown 內容。"""

    def __init__(self, max_chunk_size: int = 1500):
        self.max_chunk_size = max_chunk_size
        # 匹配 #, ##, ### 等標題
        self.header_pattern = re.compile(r"^(#+)\s+(.+)$", re.MULTILINE)

    def split(self, text: str, source_metadata: dict | None = None) -> List[Chunk]:
        """將文字依照標題切分為多個 Chunk。"""
        if not text:
            return []

        metadata = source_metadata or {}
        chunks = []
        
        # 尋找所有標題的位置
        matches = list(self.header_pattern.finditer(text))
        
        if not matches:
            # 沒有標題，直接依據長度切分 (簡單 fallback)
            return self._simple_split(text, metadata)

        last_pos = 0
        current_headers = {} # 儲存當前層級的標題內容

        for i, match in enumerate(matches):
            start = match.start()
            
            # 處理上一個標題到這一個標題之間的內容
            if start > last_pos:
                content = text[int(last_pos):int(start)].strip()
                if content:
                    chunk_meta = metadata.copy()
                    chunk_meta.update(current_headers)
                    chunks.append(Chunk(text=content, metadata=chunk_meta))

            # 更新當前層級標題
            level = len(match.group(1))
            header_text = match.group(2).strip()
            
            # 清除比當前更深層級的標題
            current_headers = {k: v for k, v in current_headers.items() if int(k[1:]) < level}
            current_headers[f"h{level}"] = header_text
            
            last_pos = start
            
        # 處理最後一部分
        content = text[int(last_pos):].strip()
        if content:
            chunk_meta = metadata.copy()
            chunk_meta.update(current_headers)
            chunks.append(Chunk(text=content, metadata=chunk_meta))

        return chunks

    def _simple_split(self, text: str, metadata: dict) -> List[Chunk]:
        """簡單的段落切分 fallback。"""
        paragraphs = text.split("\n\n")
        chunks = []
        current_text = ""
        
        for p in paragraphs:
            if len(current_text) + len(p) > self.max_chunk_size and current_text:
                chunks.append(Chunk(text=current_text.strip(), metadata=metadata))
                current_text = p
            else:
                current_text += "\n\n" + p if current_text else p
                
        if current_text:
            chunks.append(Chunk(text=current_text.strip(), metadata=metadata))
            
        return chunks
