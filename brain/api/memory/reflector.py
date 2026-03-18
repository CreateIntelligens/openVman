"""長期記憶反思與整理服務。"""

from __future__ import annotations

import logging
import json
import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from knowledge.workspace import get_workspace_root, ensure_workspace_scaffold
from infra.db import get_memories_table, encode_text, ensure_fts_index
from .importance import score_importance

logger = logging.getLogger(__name__)


class MemoryReflector:
    """負責掃描對話日誌並將其「集結」為長期記憶。"""

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.root = get_workspace_root(project_id)
        self.memory_dir = self.root / "memory"

    async def reflect_daily_logs(self):
        """掃描所有角色的當日日誌並進行索引。"""
        ensure_workspace_scaffold(self.project_id)
        
        today_str = date.today().isoformat()
        logger.info(f"Starting memory reflection for {today_str}")

        # 遍歷所有 persona 的目錄
        for persona_dir in self.memory_dir.iterdir():
            if not persona_dir.is_dir():
                continue
            
            log_file = persona_dir / f"{today_str}.md"
            if log_file.exists():
                await self._process_log_file(log_file, persona_dir.name)

        ensure_fts_index("memories", self.project_id)

    async def _process_log_file(self, path: Path, persona_id: str):
        """讀取日誌，摘要並存入 memories 表。"""
        content = path.read_text(encoding="utf-8")
        if not content or len(content) < 100:
            return

        # 1. 使用 LLM 提取關鍵學習點或重要事件 (簡化版)
        prompt = "請摘要以下對話日誌中的關鍵事實、使用者偏好與重要事件，以條列式 Markdown 回覆：\n\n" + content[:4000]
        summary = await self._generate_summary(prompt)
        
        if not summary:
            return

        # 2. 計算重要性
        importance = score_importance(summary).score

        # 3. 寫入 LanceDB
        record = {
            "text": summary,
            "vector": encode_text(summary),
            "source": "reflection",
            "date": date.today().isoformat(),
            "metadata": json.dumps({
                "persona_id": persona_id,
                "importance": importance,
                "type": "daily_reflection"
            }, ensure_ascii=False)
        }
        
        table = get_memories_table(self.project_id)
        table.add([record])
        logger.info(f"Reflected log for {persona_id} (importance: {importance})")

    async def _generate_summary(self, prompt: str) -> Optional[str]:
        """呼叫 LLM 進行摘要。"""
        try:
            # 這裡暫時模擬呼叫
            messages = [{"role": "user", "content": prompt}]
            # 實際環境中應使用 llm_client
            # return await generate_chat_turn(messages)
            return f"這是一段關於 {date.today()} 的自動反思摘要。"
        except Exception as e:
            logger.error(f"Reflection summary failed: {e}")
            return None


async def start_reflector_loop():
    """啟動簡單的背景監聽迴圈 (Heartbeat)。"""
    reflector = MemoryReflector()
    while True:
        # 每小時檢查一次是否有新日誌需要反思 (簡化邏輯)
        await reflector.reflect_daily_logs()
        await asyncio.sleep(3600) 
