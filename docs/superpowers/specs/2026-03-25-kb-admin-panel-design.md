# Knowledge Base Admin Panel Design

## 1. Core Goal
Build an intuitive, zero-friction Content Management System (CMS) for the openVman knowledge base. It allows clients to manage the AI's knowledge through a Notion-like interface, completely abstracting away the underlying vector database and RAG complexities.

## 2. Universal Markdown Strategy (Key Decision)
To radically simplify frontend development and maintain consistent data format for the AI:
*   **Upload & Convert**: Regardless of the uploaded file type (PDF, DOCX, XLSX), the backend will process it through Microsoft's `MarkItDown` and save it strictly as a `.md` file in the workspace.
*   **Edit in Markdown**: The frontend only ever deals with editing Markdown. This eliminates the need for complex rich-text or PDF editors.
*   **Simple Editor**: A standard `textarea` coupled with `react-markdown` for live preview is sufficient.

## 3. UI/UX Layout (Split-Pane Paradigm)
The interface follows an IDE/Notion style split view:

**Left Panel: Workspace Tree Explorer**
*   Displays the directory structure of `~/.openclaw/workspace/`.
*   **Actions**: Create folder, Rename, Delete, Drag & Drop to move files.
*   **Status Indicators**: Simple visual cues next to files indicating their indexing status (e.g., Green dot for "Indexed & Ready", Yellow spinner for "Processing").

**Right Panel: Main Content Area**
*   **Folder Selected**: Shows a grid/list of files in the current folder. Features a large "Dropzone" for bulk file uploads.
*   **Document Selected**:
    *   Opens the Universal Markdown Editor (split-screen: raw text on left, rendered preview on right).
    *   **Auto-Save / Save Button**: Clicking save pushes the markdown content to the backend.
    *   **Auto-Indexing**: Saving a document automatically triggers a background re-index in LanceDB. The user does not need to manually manage embeddings.

## 4. Core Workflows
1.  **Ingestion**: User drops `company_handbook.pdf` -> Frontend calls upload API -> Backend saves as `company_handbook.md` (via MarkItDown) and queues indexing -> UI shows file as ready.
2.  **Editing**: User clicks `company_handbook.md` -> Fixes a typo in the markdown editor -> Clicks Save -> Backend updates file and re-indexes -> AI instantly knows the updated fact.
3.  **Organization**: User creates a `Policies/` folder and drags markdown files into it.

## 5. Technical Stack
*   **Framework**: React 18 + Vite (Existing `frontend/admin` setup).
*   **Styling**: Tailwind CSS.
*   **Components**: `radix-ui` (recommended for headless accessible components like Tree, Dialog, Dropdown).
*   **Markdown Handling**: `react-markdown` (already in `package.json`).
*   **State Management**: React Context or Zustand for managing the active selected file and tree state.

## 6. Integration Points (Backend APIs required)
*   `GET /brain/knowledge/base/documents` (Tree structure)
*   `GET /brain/knowledge/document?path=...` (Read MD)
*   `PUT /brain/knowledge/document` (Save MD)
*   `POST /brain/knowledge/upload` (Upload raw files)
*   `DELETE /brain/knowledge/document`
*   `POST /brain/knowledge/move`
