# kb-file-management Specification

## Purpose
Define how the knowledge base file manager uploads, displays, and operates on workspace files while keeping Markdown as the canonical editable knowledge format.
## Requirements
### Requirement: File Upload
The system SHALL allow users to upload files into the currently selected directory.

#### Scenario: Bulk Upload via Dropzone
- **WHEN** the user drags and drops multiple files into the main content area dropzone
- **THEN** the system uploads each file to the backend `upload` endpoint
- **THEN** UTF-8 text and markdown files are forwarded directly to Brain
- **THEN** office documents are preserved as source artifacts and converted into Markdown through the Docling-based ingestion pipeline before indexing
- **THEN** the knowledge management UI continues to expose Markdown as the primary editable document form

#### Scenario: Upload conversion failure for office documents
- **WHEN** the user uploads a PDF, DOCX, PPTX, or XLSX file and the Docling-based ingestion pipeline fails
- **THEN** the system surfaces a clear upload failure instead of pretending the file was indexed successfully

### Requirement: Directory Navigation
The system SHALL allow users to navigate the workspace directory structure.

#### Scenario: Expanding a Folder
- **WHEN** the user clicks on a folder in the sidebar tree
- **THEN** the tree expands to show the contents of that folder

### Requirement: File Operations
The system SHALL allow users to delete, rename, and move files and folders.

#### Scenario: Deleting a File
- **WHEN** the user right-clicks a file and selects "Delete"
- **THEN** the system prompts for confirmation, deletes the file via the backend API, and removes it from the UI
