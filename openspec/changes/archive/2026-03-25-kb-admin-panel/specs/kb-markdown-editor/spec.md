## ADDED Requirements

### Requirement: Universal Markdown Editing
The system SHALL only allow editing of Markdown (`.md`) files in the frontend editor.

#### Scenario: Selecting a Markdown File
- **WHEN** a user clicks on a `.md` file in the tree view
- **THEN** the main content area opens the Universal Markdown Editor displaying the file's raw content alongside a rendered preview

### Requirement: Auto-Save and Index Trigger
The system SHALL automatically trigger a save operation and subsequent background RAG re-indexing when the user initiates a save action.

#### Scenario: Manual Save
- **WHEN** the user modifies the markdown text and clicks the "Save" button
- **THEN** the system sends a `PUT` request to update the file content on the server
- **THEN** the server automatically triggers the re-indexing pipeline for that document

### Requirement: MarkItDown Abstraction
The system SHALL abstract the conversion of non-markdown files.

#### Scenario: Viewing a PDF
- **WHEN** a user uploads a PDF and selects the resulting generated `.md` file
- **THEN** they see the Markdown representation of the PDF content ready for editing, without needing a PDF viewer
