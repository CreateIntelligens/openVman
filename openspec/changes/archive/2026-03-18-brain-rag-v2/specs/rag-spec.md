# Specifications: Knowledge & Memory v2

## Directory Layout
| Path | Purpose |
|------|---------|
| `brain/workspace/raw/` | 放置原始檔案 (PDF, DOCX, MP3, etc.) |
| `brain/workspace/knowledge/` | 放置轉出的 Markdown 片段，由 Ingestion Manager 維護 |
| `brain/workspace/personas/` | 放置角色設定 (SOUL.md) |
| `brain/workspace/memory/` | 放置每日對話紀錄 (YYYY-MM-DD.md) |

## Ingestion Flow (Pseudo-Code)
1. **Detect**: `file_in_raw`
2. **Convert**: `markitdown_result = MarkItDown().convert(file_in_raw)`
3. **Save**: `write_to_knowledge(file_in_raw.name + ".md", markitdown_result.text_content)`
4. **Chunk**: `chunks = HeaderBasedChunker().split(markitdown_result.text_content)`
5. **Index**: `for chunk in chunks: table.add([{"text": chunk, "vector": embed(chunk), "metadata": {source_file: file_in_raw}}])`
6. **Refresh**: `table.create_fts_index("text", replace=True)`

## Retrieval Specification (Hybrid Search)
當調用 `retrieve_context` 時，預設應傳入 `query_text` 以啟動混合檢索：
- **Vector Search**: 尋找概念相近的內容。
- **BM25 Search**: 尋找包含特定字詞 (如 "TX-500", "David") 的內容。
- **Reranking**: 先取出 Top-K 候選人，再根據時間衰減與重要性分數細排。

## Memory Reflector
- 觸發時機: 每日 00:00 (Cron) 或 Session 閒置 30 分鐘。
- 邏輯: 讀取當日日誌，使用 LLM 摘要關鍵學習點 (`LEARNINGS.md`)，並將重要情節索引回 `memories` 向量表。
