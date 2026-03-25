## Why

The openVman system requires a user-friendly Knowledge Base Admin Panel to allow clients to easily manage the AI's underlying knowledge. Currently, managing the knowledge base requires technical intervention. Providing a dedicated CMS (Content Management System) will empower clients to directly upload, edit, and organize files, abstracting away the complexities of vector databases and RAG (Retrieval-Augmented Generation) indexing.

## What Changes

- Introduce a new web-based admin interface for knowledge base management.
- Implement a split-pane UI featuring a directory tree explorer and a main content area.
- Establish a "Universal Markdown" workflow: all uploaded documents (PDF, DOCX, etc.) are automatically converted to Markdown via the backend `MarkItDown` service.
- Integrate a Markdown editor in the frontend for direct content modification.
- Automate the indexing process so that saving a document automatically triggers a background RAG re-index, hiding this complexity from the user.
- Provide clear visual status indicators for document indexing readiness.

## Capabilities

### New Capabilities
- `kb-admin-ui`: The frontend React application providing the split-pane file explorer and markdown editor interface for managing the workspace.
- `kb-markdown-editor`: The specific capability of editing markdown files directly within the admin panel, including auto-save and index triggering.
- `kb-file-management`: The capability to upload, move, rename, and delete files and folders within the workspace via the UI.

### Modified Capabilities
- `<none>`

## Impact

- **Frontend**: Significant additions to the `frontend/admin` directory (React, Vite, Tailwind).
- **Backend APIs**: Requires new or verified REST endpoints for file manipulation (`GET` tree, `POST` upload, `PUT` save, `DELETE`, `POST` move) that interact with the `brain/knowledge` system.
- **System Flow**: Changes the primary method of data ingestion from manual backend processes to client-driven frontend actions.
