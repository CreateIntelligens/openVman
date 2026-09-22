## ADDED Requirements

### Requirement: Knowledge file operations require an accessible project
The system SHALL authenticate every knowledge operation and SHALL resolve the selected project against ownership or an explicit temporary-account grant before listing, uploading, reading, saving, moving, deleting, reindexing, rebuilding graph data, or reading Quick QA／quick reply content.

#### Scenario: User opens an owned knowledge base
- **WHEN** an authenticated user navigates to a project they own
- **THEN** directory and document results are read only from that project's workspace

#### Scenario: User fabricates another project ID
- **WHEN** an authenticated user sends a knowledge request with a project ID owned by another account
- **THEN** the system returns 404 before reading or mutating any workspace, index, metadata, QA, raw file, or graph artifact

#### Scenario: Upload is scoped to the resolved project
- **WHEN** an authenticated user uploads or imports a document into an owned project
- **THEN** conversion, raw storage, canonical Markdown, QA artifacts, indexing, and graph updates all use that same server-resolved project context

#### Scenario: ESG quick replies are requested
- **WHEN** an account with access to project `esg-7dea843a0d` opens quick reply
- **THEN** the response contains only that project's visible Quick QA nodes and entries

#### Scenario: ESG project is not granted
- **WHEN** a temporary account without the ESG project grant requests its Quick QA tree, merged entries, or images
- **THEN** the system returns 404 before reading any ESG knowledge artifact
