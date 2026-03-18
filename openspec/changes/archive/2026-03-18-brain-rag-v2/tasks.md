# Implementation Tasks: Knowledge & Memory v2 (RAG v2)

## 1. Core Services & Ingestion
- [x] 1.1 Add `markitdown` to `requirements.txt` <!-- id: 401 -->
- [x] 1.2 Implement `MarkItDownService` in `brain/api/knowledge/markitdown_service.py` <!-- id: 402 -->
- [x] 1.3 Implement `IngestionManager` with file watching or scheduled scanning <!-- id: 403 -->
- [x] 1.4 Refine `HeaderBasedChunker` for better semantic splitting <!-- id: 404 -->

## 2. Database & Retrieval Enhancements
- [x] 2.1 Update `infra/db.py` to automatically manage FTS indices for `knowledge` and `memories` <!-- id: 501 -->
- [x] 2.2 Formalize hybrid search call in `memory/retrieval.py` with score normalization <!-- id: 502 -->
- [x] 2.3 Add "importance" scoring logic for memory entries (Reflective loop) <!-- id: 503 -->

## 3. Testing & Verification
- [x] 3.1 Verify PDF to Markdown transformation via `markitdown` <!-- id: 601 -->
- [x] 3.2 Add integration tests verifying hybrid search returns more relevant results for keyword-heavy queries <!-- id: 602 -->
- [x] 3.3 Verify daily log reflection workflow <!-- id: 603 -->
