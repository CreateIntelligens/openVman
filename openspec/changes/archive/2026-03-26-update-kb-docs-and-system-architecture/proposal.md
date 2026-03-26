# Proposal: Update KB Admin Panel Documentation & System Architecture

## Why

The Knowledge Base (KB) Admin Panel was implemented, but the core documentation in the `docs/` directory has not been fully updated to reflect these changes. Specifically, the backend and frontend specifications need to incorporate the new KB management workflows (Markdown strategy, file tree explorer, indexing). Additionally, there is a need for a "General Architecture" document to provide a holistic view of the system beyond the "Nervous System" focus, and an "API / WS Linkage" document to describe the interaction between components.

## What Changes

- Update `01_BACKEND_SPEC.md` to include KB-related API endpoints and integration details.
- Update `02_FRONTEND_SPEC.md` to include the KB Admin Panel UI/UX (Split-Pane, Markdown editor) and its state management.
- Create `00_SYSTEM_ARCHITECTURE.md` (General Architecture) to provide a high-level overview of the entire openVman ecosystem.
- Create `09_API_WS_LINKAGE.md` (API/WS Linkage) to map out how different parts of the system communicate.
- Ensure all documents in `docs/` are synchronized with the recent `2026-03-25-kb-admin-panel` design decisions.

## Capabilities

### New Capabilities
- `system-architecture-doc`: Comprehensive overview of the system components and their relationships.
- `api-ws-linkage-doc`: Detailed mapping of REST and WebSocket interactions across the system.
- `kb-admin-rationale-doc`: Detailed explanation of KB Admin features and design rationale (the "Why").

### Modified Capabilities
- `backend-spec`: Enhanced with Knowledge Base management API requirements.
- `frontend-spec`: Enhanced with KB Admin Panel UI requirements.

## Impact

- **Documentation**: Significant improvement in onboarding and system understanding for team members.
- **Consistency**: Ensures the `docs/` folder accurately represents the current state of the codebase.
- **Future Development**: Provides a solid foundation for further scaling and feature integration.
