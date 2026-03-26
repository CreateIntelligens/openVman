## ADDED Requirements

### Requirement: backend-kb-api-update
`01_BACKEND_SPEC.md` must be updated to include the Knowledge Base management endpoints (`/brain/knowledge/...`).

#### Scenario: spec-sync
- **WHEN** reading `01_BACKEND_SPEC.md`
- **THEN** the KB management section should match the implemented design from `2026-03-25-kb-admin-panel`.

### Requirement: frontend-kb-ui-update
`02_FRONTEND_SPEC.md` must be updated to include the "KB Admin Panel" section, describing the split-pane layout and markdown editor strategy.

#### Scenario: spec-sync
- **WHEN** reading `02_FRONTEND_SPEC.md`
- **THEN** the "Media Upload Workflow" section should be expanded to include Knowledge Base specific details.
