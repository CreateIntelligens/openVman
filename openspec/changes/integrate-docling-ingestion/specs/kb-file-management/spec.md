## MODIFIED Requirements

### Requirement: File Upload
The system SHALL allow users to upload files into the currently selected directory.

#### Scenario: Bulk Upload via Dropzone
- **WHEN** the user drags and drops multiple files into the main content area dropzone
- **THEN** the system uploads each file to the backend `upload` endpoint
- **THEN** UTF-8 text and markdown files are forwarded directly to Brain
- **THEN** office documents are preserved as source artifacts and converted into Markdown through the Docling-based ingestion pipeline before indexing
- **THEN** the knowledge management UI continues to expose Markdown as the primary editable document form

#### Scenario: Upload conversion failure for office documents
- **WHEN** the user uploads a PDF, DOCX, or PPTX file and the Docling-based ingestion pipeline fails
- **THEN** the system surfaces a clear upload failure instead of pretending the file was indexed successfully
