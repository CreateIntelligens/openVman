# Design: Update KB Admin Panel Documentation & System Architecture

## Context

The system has evolved to include a comprehensive Knowledge Base Admin Panel, but the core specifications in the `docs/` folder still describe an earlier state. The existing `01_BACKEND_SPEC.md` and `02_FRONTEND_SPEC.md` lack details on the Markdown-based KB management, the split-pane editor, and the recursive tree indexing. Furthermore, there is no high-level architecture document that ties all components together, nor is there a dedicated API/WS linkage document.

## Goals / Non-Goals

**Goals:**
- Synchronize `docs/01_BACKEND_SPEC.md` with KB API endpoints (`/brain/knowledge/...`).
- Synchronize `docs/02_FRONTEND_SPEC.md` with KB Admin Panel UI/UX (Split-Pane, Markdown Strategy).
- Create a foundational `docs/00_SYSTEM_ARCHITECTURE.md` (General Architecture) replacing or complementing the nervous system doc.
- [ ] Create `docs/09_API_WS_LINKAGE.md` to document cross-component communication.
- [ ] Create `docs/superpowers/specs/2026-03-26-kb-admin-panel-rationale.md` to explain features and design "Why".

**Non-Goals:**
- Refactoring the actual code (this is a documentation-only change).
- Creating detailed per-function API documentation (OxyGen/OpenAPI is separate).

## Decisions

1. **Hierarchy**: Use `00_SYSTEM_ARCHITECTURE.md` as the entry point for all developers.
2. **Component Isolation**: Keep `01_BACKEND_SPEC.md` focused on the "Nervous System" and "发声器官", but add the "Knowledge Management" section as a core dependency.
3. **Markdown Strategy**: Explicitly document the "Universal Markdown Strategy" in both frontend and backend specs to ensure future consistency.
4. **Rationale Document**: This new document will provide the business and technical context for the KB Admin Panel, explaining why we chose the split-pane approach and the automated indexing flow.
5. **Linkage Mapping**: Use mermaid diagrams (if possible in markdown) or structured tables to show the flow between Frontend <=> Backend <=> Gateway <=> Brain.

## Risks / Trade-offs

- **Risk**: Documentation becoming stale again if not updated during implementation.
- **Trade-off**: Choosing to keep the documents in `docs/` high-level vs. highly technical. The decision is to keep them as "architectural blueprints" rather than API references.
