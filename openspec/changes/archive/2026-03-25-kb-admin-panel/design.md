## Context

Currently, the openVman system relies on backend file system manipulation to manage the knowledge base (RAG documents). As the system transitions to client use, a dedicated, user-friendly frontend interface is required. The system already has a robust backend infrastructure including `MarkItDown` for document conversion and LanceDB for vector storage.

## Goals / Non-Goals

**Goals:**
- Build a React-based Admin UI with a split-pane layout (Tree Explorer + Content Area).
- Implement a "Universal Markdown" strategy where all files are converted and edited as Markdown.
- Automate the indexing process upon document save.
- Provide simple visual cues for document indexing status.

**Non-Goals:**
- Creating a complex WYSIWYG rich-text editor or PDF editor.
- Exposing the granular details of vector chunks or embeddings to the end-user.
- Complex user role management within this specific feature scope.

## Decisions

- **Universal Markdown Strategy**: All uploaded files (PDF, DOCX) will be converted to `.md` via the backend `MarkItDown` service. 
    - *Rationale*: Radically simplifies the frontend editor requirements and maintains a consistent, easily editable data format for the AI.
- **Split-Pane Layout**: The UI will use a standard IDE/Notion layout.
    - *Rationale*: Provides the best balance between navigating a complex folder structure and editing content efficiently.
- **Auto-Sync Indexing**: Saving a `.md` file automatically triggers a background re-index in LanceDB.
    - *Rationale*: Abstracts away the complexity of RAG from the non-technical client, treating the knowledge base like a standard filesystem that happens to power an AI.
- **Technology Stack**: React 18, Vite, Tailwind CSS, `react-markdown`.
    - *Rationale*: Leverages the existing `frontend/admin` stack for rapid development.

## Risks / Trade-offs

- [Risk] **Markdown formatting errors**: Users might struggle with raw Markdown syntax if they are used to MS Word.
  → *Mitigation*: Provide clear live-preview using `react-markdown` and potentially add simple toolbar buttons (bold, italic, link) that insert markdown syntax into the textarea.
- [Risk] **Upload and conversion latency**: Large PDFs might take time to process via `MarkItDown`.
  → *Mitigation*: Implement clear asynchronous status indicators (yellow spinner) so the user knows processing is happening in the background.
