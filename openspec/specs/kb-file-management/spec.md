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
- **WHEN** the user uploads a PDF, DOCX, PPTX, or XLSX file and the document conversion pipeline fails
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
