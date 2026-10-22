import ConfirmModal from "../components/ConfirmModal";
import WorkspaceDesktopSidebar from "../components/workspace/WorkspaceDesktopSidebar";
import WorkspaceEditor from "../components/workspace/WorkspaceEditor";
import WorkspaceMobileSidebar from "../components/workspace/WorkspaceMobileSidebar";
import { useNavigationGuard, useUnsavedChanges } from "../context/NavigationGuardContext";
import { useWorkspaceManager } from "../hooks/useWorkspaceManager";

export default function Workspace() {
  const {
    confirmDeleteDocument,
    createDocument,
    deleteTarget,
    docSearch,
    documents,
    draftContent,
    draftPath,
    dragOver,
    editorMode,
    handleDrop,
    handleFileUpload,
    hasUnsavedChanges,
    loadDocuments,
    loadedContent,
    loadedPath,
    loadingDocument,
    loadingList,
    mobileSidebarOpen,
    openDocument,
    saving,
    saveDocument,
    selectedPath,
    setDeleteTarget,
    setDocSearch,
    setDraftContent,
    setDraftPath,
    setDragOver,
    setEditorMode,
    setMobileSidebarOpen,
    status,
    syncing,
    syncDocuments,
    uploading,
    uploadInputRef,
  } = useWorkspaceManager();
  useUnsavedChanges("workspace-editor", hasUnsavedChanges, "Workspace 文件");
  const { requestNavigation } = useNavigationGuard();

  // 換文件、開新文件、重新整理都會蓋掉編輯區，有未存的修改先問。
  const selectDocument = (path: string) => {
    if (path === selectedPath) return;
    requestNavigation(() => void openDocument(path));
  };
  const startNewDocument = () => requestNavigation(createDocument);

  return (
    <div
      className="flex h-full w-full overflow-hidden bg-surface dark:bg-background-dark"
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <WorkspaceMobileSidebar
        open={mobileSidebarOpen}
        documents={documents}
        selectedPath={selectedPath}
        loadingList={loadingList}
        docSearch={docSearch}
        onClose={() => setMobileSidebarOpen(false)}
        onCreate={startNewDocument}
        onSearchChange={setDocSearch}
        onSelect={(path) => {
          setMobileSidebarOpen(false);
          selectDocument(path);
        }}
      />

      <WorkspaceDesktopSidebar
        documents={documents}
        selectedPath={selectedPath}
        loadingList={loadingList}
        syncing={syncing}
        uploading={uploading}
        docSearch={docSearch}
        uploadInputRef={uploadInputRef}
        onRefresh={() => requestNavigation(() => void loadDocuments())}
        onSync={() => void syncDocuments()}
        onCreate={startNewDocument}
        onSearchChange={setDocSearch}
        onSelect={selectDocument}
        onFileUpload={handleFileUpload}
      />

      <WorkspaceEditor
        documentsCount={documents.length}
        dragOver={dragOver}
        status={status}
        selectedPath={selectedPath}
        draftPath={draftPath}
        draftContent={draftContent}
        editorMode={editorMode}
        loadingDocument={loadingDocument}
        hasUnsavedChanges={hasUnsavedChanges}
        saving={saving}
        canSave={Boolean(draftPath.trim() && (hasUnsavedChanges || draftPath !== loadedPath))}
        onOpenSidebar={() => setMobileSidebarOpen(true)}
        onDraftPathChange={setDraftPath}
        onDraftContentChange={setDraftContent}
        onDelete={() => setDeleteTarget(selectedPath)}
        onEditorModeChange={setEditorMode}
        onDiscard={() => {
          setDraftPath(loadedPath);
          setDraftContent(loadedContent);
        }}
        onSave={() => void saveDocument()}
      />

      <ConfirmModal
        open={deleteTarget !== ""}
        title="Delete Document"
        message={`確定要刪除「${deleteTarget}」嗎？\n\n此操作無法復原。`}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDeleteDocument}
        onCancel={() => setDeleteTarget("")}
      />
    </div>
  );
}
