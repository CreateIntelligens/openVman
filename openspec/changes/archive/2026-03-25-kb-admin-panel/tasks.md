## 1. Setup and Project Scaffold

- [x] 1.1 Scaffold the basic React Admin UI layout components (Sidebar, Main Area).
- [x] 1.2 Setup routing if necessary (e.g., using `react-router-dom`) for handling folder paths in the URL.
- [x] 1.3 Install and configure essential UI component libraries (e.g., `radix-ui/react-dialog`, `lucide-react` for icons).

## 2. API Integration Layer

- [x] 2.1 Create an API client service in the frontend to interact with `/brain/knowledge/base/documents` to fetch the workspace tree.
- [x] 2.2 Create API functions for document CRUD operations (`GET`, `PUT`, `DELETE`).
- [x] 2.3 Create an API function to handle file uploads to the backend (`POST /brain/knowledge/upload`).

## 3. Sidebar Tree Explorer (kb-admin-ui)

- [x] 3.1 Implement a recursive Tree Component to render the folder/file structure fetched from the backend.
- [x] 3.2 Implement visual status indicators (dots/spinners) next to filenames based on indexing metadata.
- [x] 3.3 Add context menu or action buttons for "New Folder", "Rename", and "Delete" operations.

## 4. Main Content Area & Universal Markdown Editor (kb-markdown-editor)

- [x] 4.1 Implement a bulk upload Dropzone component when a folder is selected in the tree.
- [x] 4.2 Integrate `react-markdown` to render the `.md` content when a file is selected.
- [x] 4.3 Create a split-screen Editor Component (raw textarea on the left, rendered markdown on the right).
- [x] 4.4 Implement the "Save" action: take textarea content, send `PUT` to backend, and trigger re-index flow.

## 5. End-to-End Workflows & Polish (kb-file-management)

- [x] 5.1 Connect the Dropzone to the backend upload endpoint and handle the "processing" state while MarkItDown converts the file.
- [x] 5.2 Implement optimistic UI updates (e.g., showing a file in the tree immediately upon successful upload, while it indexes in the background).
- [x] 5.3 Implement Drag and Drop functionality within the Tree Component to allow moving files between folders.
