## ADDED Requirements

### Requirement: Split-Pane Layout
The system SHALL provide a split-pane layout consisting of a left sidebar for directory navigation and a right main area for content display.

#### Scenario: Initial Load
- **WHEN** the user navigates to the Knowledge Base Admin Panel
- **THEN** the system displays the root workspace directory structure in the left sidebar and an empty state or dashboard in the main area

### Requirement: Indexing Status Indicators
The system SHALL display visual indicators next to files in the tree view to represent their indexing status in LanceDB.

#### Scenario: File Processing
- **WHEN** a file is currently being chunked and embedded by the backend
- **THEN** the UI displays a "processing" indicator (e.g., yellow spinner) next to the filename

#### Scenario: File Ready
- **WHEN** a file has been successfully indexed in LanceDB
- **THEN** the UI displays a "ready" indicator (e.g., green dot) next to the filename
