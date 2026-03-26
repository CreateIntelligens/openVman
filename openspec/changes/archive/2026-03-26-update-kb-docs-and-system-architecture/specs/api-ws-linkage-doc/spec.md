## ADDED Requirements

### Requirement: api-ws-mapping
The document must map out all REST API endpoints and WebSocket events used in the system, categorizing them by component.

#### Scenario: route-discovery
- **WHEN** a developer needs to find the Knowledge Base upload endpoint
- **THEN** it should be listed under the "Gateway" or "Brain" section with its URL and method.

### Requirement: sequence-diagrams
The document must provide sequence diagrams for core workflows:
1. Conversational Chat (WS)
2. KB Document Upload & Indexing (REST + WS notification)

#### Scenario: workflow-understanding
- **WHEN** viewing the KB Upload sequence
- **THEN** it should show Frontend -> Gateway (Upload) -> Backend (Enrich notification) -> Brain (Indexing) -> Frontend (Status update).
