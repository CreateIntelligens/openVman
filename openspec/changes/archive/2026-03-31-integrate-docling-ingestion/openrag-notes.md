# OpenRAG Reference Notes

## Purpose

Capture what openVman should borrow from OpenRAG for this change, and what remains explicitly out of scope.

## Adopt

- Use `docling-serve` as a dedicated document conversion service instead of embedding heavy parsing dependencies into Brain.
- Keep document conversion as an ingestion concern rather than a retrieval concern.
- Treat high-quality Markdown as the canonical representation that downstream chunking and indexing consume.
- Preserve explicit timeout, error handling, and observability around document conversion requests.

## Do Not Adopt

- Do not import or depend on the OpenRAG repository as a platform base.
- Do not introduce OpenSearch as a storage backend.
- Do not introduce Langflow orchestration or rework openVman around OpenRAG's full application architecture.
- Do not replace existing Brain, Gateway, LanceDB, or KB Admin boundaries.

## Implication For This Change

This change is a targeted ingestion upgrade for openVman:

- `workspace/raw/` stores uploaded source artifacts
- Docling produces Markdown into `workspace/knowledge/`
- Brain continues indexing Markdown into LanceDB

The goal is to improve document conversion quality while preserving openVman's existing system design.
