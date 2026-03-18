# Changelog

## [0.3.0] - 2026-03-18

### Added
- **RAG v2 Architecture**: Transitioned to a multi-modal, hybrid search architecture.
- **MarkItDown Integration**: Support for PDF, DOCX, XLSX, and more via `MarkItDownService`.
- **Header-Based Chunker**: Semantic splitting based on Markdown headers (H1-H3).
- **Hybrid Search (BM25)**: Enabled combined vector and text search in LanceDB.
- **Memory Reflector**: Automated daily log processing for long-term memory extraction.
- **API Expansion**: New endpoints for knowledge sync (`/api/admin/knowledge/sync`) and memory reflection (`/api/admin/memory/reflect`).
- **Hybrid Search API**: Enhanced `/api/search` to support `query_type` parameter.

### Changed
- Moved root specification files to the `docs/` directory for better organization.
- Updated `readme.md` with RAG v2 highlights and doc map.


## [0.2.0] - 2026-03-18

### Added
- **Brain Skills System**: Implementation of a modular plugin system in `brain/skills/`. Supports dynamic tool registration with namespacing.
- **LLM Failover (DR Mode)**: Formalized `fallback_chain` logic for cross-provider and cross-model failover (Gemini, OpenAI, Groq).
- **ToolRegistry Enhancements**: Support for dynamic skill-provided tools.
- **Example Skill**: Added a `weather` skill at `brain/skills/weather/` for verification.
- **Unit Testing**: Added `test_skills.py` for verifying the skill management system.

### Changed
- Updated `03_BRAIN_SPEC.md` to include Skills System and Failover specifications.
- Updated `README.md` with the latest architecture highlights.
- Adjusted `requirements.txt` to include `PyYAML` for skill manifest parsing.

## [0.1.0] - 2026-03-11

### Added
- Initial architecture specifications (00-03).
- Basic project structure for Backend, Brain, and Frontend.
- core-protocol defined for WebSocket JSON communication.
- Initial project plan (08_PROJECT_PLAN_2MONTH.md).
