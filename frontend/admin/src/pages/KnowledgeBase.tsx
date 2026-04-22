import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigation } from "../context/NavigationContext";
import ConfirmModal from "../components/ConfirmModal";
import StatusAlert from "../components/StatusAlert";
import FileView from "../components/kb/FileView";
import GraphView from "../components/kb/GraphView";
import MoveModal from "../components/kb/MoveModal";
import NoteModal from "../components/kb/NoteModal";
import SourcePanel from "../components/kb/SourcePanel";
import TreeView from "../components/kb/TreeView";
import type { TreeNode } from "../components/kb/helpers";
import { isUploadDerivedKnowledgeFile } from "../components/kb/helpers";
import { useKnowledgeBase } from "../hooks/useKnowledgeBase";

export default function KnowledgeBase() {
  const {
    documents,
    serverDirs,
    loading,
    reindexing,
    uploading,
    status,
    search,
    selectedPath,
    rightPane,
    openDocument,
    editContent,
    editLoading,
    saving,
    editorDirty,
    deleteTarget,
    movingPath,
    showNewFolder,
    newFolderName,
    showSourcePanel,
    activeSourceMode,
    crawlUrlValue,
    crawling,
    showNoteModal,
    noteTitle,
    noteContent,
    creatingNote,
    dragOver,
    uploadInputRef,
    filteredTree,
    visibleExpandedDirs,
    hasActiveSearch,
    currentDir,
    indexedCount,
    matchingDocumentCount,
    setStatus,
    setSearch,
    setDeleteTarget,
    setMovingPath,
    setShowNewFolder,
    setNewFolderName,
    setShowSourcePanel,
    setActiveSourceMode,
    setCrawlUrlValue,
    setShowNoteModal,
    setNoteTitle,
    setNoteContent,
    toggleExpand,
    handleTreeSelect,
    handleSave,
    handleFileUpload,
    handleReindex,
    handleCrawl,
    handleDeleteConfirm,
    handleMove,
    handleToggleEnabled,
    handleCreateNote,
    handleCreateFolderSubmit,
    cancelCreateFolder,
    closeNoteModal,
    closeFileView,
    updateEditContent,
    handleDragEnter,
    handleDragLeave,
    handleDrop,
  } = useKnowledgeBase();
  const [draggingPath, setDraggingPath] = useState<string | null>(null);
  const [dropTargetPath, setDropTargetPath] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"documents" | "graph">("documents");
  const { pendingToken, consumeSubView } = useNavigation();
  useEffect(() => {
    const view = consumeSubView("KnowledgeBase");
    if (view === "graph" || view === "documents") {
      setActiveTab(view);
    }
  }, [pendingToken, consumeSubView]);

  const sourceDragDir = useMemo(
    () => draggingPath ? draggingPath.split("/").slice(0, -1).join("/") : "",
    [draggingPath],
  );
  const hasMatchingTreeNodes = filteredTree.children.length > 0;
  const showSearchEmptyState = hasActiveSearch && !hasMatchingTreeNodes;
  const deleteTargetDocument = useMemo(
    () => (deleteTarget?.type === "file" ? documents.find((document) => document.path === deleteTarget.value) ?? null : null),
    [deleteTarget, documents],
  );
  const isUploadDerived = !!deleteTargetDocument && isUploadDerivedKnowledgeFile(deleteTargetDocument);
  const deleteMessage = deleteTarget?.type === "dir"
    ? `確定要刪除資料夾 ${deleteTarget.value} 嗎？`
    : isUploadDerived
      ? `確定要刪除 ${deleteTarget?.value} 嗎？這只會移除知識文件與索引；原始上傳檔仍保留在 raw/。`
      : `確定要刪除 ${deleteTarget?.value} 嗎？`;

  const handleTreeDragStart = useCallback((node: TreeNode) => {
    setDraggingPath(node.path);
  }, []);

  const handleTreeDragEnd = useCallback(() => {
    setDraggingPath(null);
    setDropTargetPath(null);
  }, []);

  const handleTreeDrop = useCallback(async (targetDir: string) => {
    setDraggingPath((path) => {
      if (!path) return null;
      setDropTargetPath(targetDir);
      handleMove(path, targetDir).then(() => {
        setDraggingPath(null);
        setDropTargetPath(null);
      });
      return null;
    });
  }, [handleMove]);

  return (
    <div
      className="h-full flex flex-col overflow-hidden bg-slate-50 dark:bg-background-dark"
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragOver && (
        <div className="fixed inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-white dark:bg-slate-900 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">upload_file</span>
            <span className="text-xl font-bold text-slate-900 dark:text-white">拖放檔案以上傳到 {currentDir}</span>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800/60 shrink-0">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary text-[24px]">school</span>
          <h1 className="text-lg font-bold text-slate-900 dark:text-white">知識庫</h1>
          <span className="text-xs text-slate-500">{documents.length} 文件 · {indexedCount} 已索引</span>
          <div className="ml-3 flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-100 dark:bg-slate-900/40 p-0.5">
            <button
              onClick={() => setActiveTab("documents")}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
                activeTab === "documents"
                  ? "bg-white dark:bg-slate-800 text-primary shadow-sm"
                  : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
              }`}
            >
              文件
            </button>
            <button
              onClick={() => setActiveTab("graph")}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
                activeTab === "graph"
                  ? "bg-white dark:bg-slate-800 text-primary shadow-sm"
                  : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
              }`}
            >
              圖譜
            </button>
          </div>
        </div>
        {activeTab === "documents" && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowSourcePanel(!showSourcePanel)}
              className="flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/15 transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">add</span>
              新增來源
            </button>
            <button
              onClick={handleReindex}
              disabled={reindexing}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[16px] ${reindexing ? "animate-spin" : ""}`}>sync</span>
              {reindexing ? "索引中..." : "重新索引"}
            </button>
          </div>
        )}
      </div>

      {status && (
        <div className="px-4 pt-2 shrink-0">
          <StatusAlert type={status.type} message={status.message} onDismiss={() => setStatus(null)} />
        </div>
      )}

      {activeTab === "graph" ? (
        <GraphView />
      ) : (
      <>
      {showSourcePanel && (
        <SourcePanel
          activeMode={activeSourceMode}
          setActiveMode={setActiveSourceMode}
          uploading={uploading}
          uploadInputRef={uploadInputRef}
          currentDir={currentDir}
          crawlUrlValue={crawlUrlValue}
          setCrawlUrlValue={setCrawlUrlValue}
          crawling={crawling}
          onCrawl={handleCrawl}
          onShowNote={() => setShowNoteModal(true)}
        />
      )}

      <input type="file" ref={uploadInputRef} onChange={handleFileUpload} className="hidden" multiple />

      <div className="flex-1 flex min-h-0 overflow-hidden">
        <aside className="w-64 xl:w-72 shrink-0 border-r border-slate-200 dark:border-slate-800/60 flex flex-col bg-white dark:bg-slate-950/30 overflow-hidden">
          <div className="px-3 py-2.5 border-b border-slate-200 dark:border-slate-800/40 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">檔案樹</span>
            <button
              onClick={() => {
                setShowNewFolder(true);
                setNewFolderName("");
              }}
              className="p-1 rounded-md text-slate-500 hover:text-primary hover:bg-primary/10 transition-colors"
              title="新增資料夾"
            >
              <span className="material-symbols-outlined text-[16px]">create_new_folder</span>
            </button>
          </div>

          <div className="border-b border-slate-200 dark:border-slate-800/40 px-3 py-2.5">
            <div className="relative">
              <span className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[16px] text-slate-400 dark:text-slate-500">
                search
              </span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜尋檔案樹..."
                className="w-full rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 py-1.5 pl-8 pr-3 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 outline-none transition-colors focus:border-primary/50"
              />
            </div>
            {hasActiveSearch && (
              <p className="mt-2 text-xs text-slate-500">搜尋命中 {matchingDocumentCount} 筆</p>
            )}
          </div>

          {showNewFolder && (
            <form onSubmit={handleCreateFolderSubmit} className="flex items-center gap-1 px-3 py-2 border-b border-slate-200 dark:border-slate-800/40 bg-primary/5">
              <input
                autoFocus
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="資料夾名稱"
                className="bg-transparent text-xs text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 outline-none flex-1 min-w-0"
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    cancelCreateFolder();
                  }
                }}
              />
              <button type="submit" disabled={!newFolderName.trim()} className="p-0.5 text-primary disabled:opacity-30">
                <span className="material-symbols-outlined text-[16px]">check</span>
              </button>
              <button type="button" onClick={cancelCreateFolder} className="p-0.5 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
                <span className="material-symbols-outlined text-[16px]">close</span>
              </button>
            </form>
          )}

          <div className="flex-1 overflow-y-auto overflow-x-hidden py-1">
            {loading && !documents.length ? (
              <div className="flex items-center justify-center py-10 text-slate-500 text-xs">
                <span className="material-symbols-outlined animate-spin mr-1 text-[16px]">refresh</span> 載入中...
              </div>
            ) : showSearchEmptyState ? (
              <div className="px-4 py-10 text-center text-xs text-slate-500">
                <span className="material-symbols-outlined mb-2 text-[20px]">search_off</span>
                <p>沒有符合搜尋的檔案</p>
              </div>
            ) : (
              <TreeView
                node={filteredTree}
                depth={0}
                selectedPath={selectedPath}
                expandedDirs={visibleExpandedDirs}
                onSelect={handleTreeSelect}
                onToggle={toggleExpand}
                draggingPath={draggingPath}
                sourceDragDir={sourceDragDir}
                dropTargetPath={dropTargetPath}
                onDragStart={handleTreeDragStart}
                onDragEnd={handleTreeDragEnd}
                onDragTargetChange={setDropTargetPath}
                onDropFile={handleTreeDrop}
              />
            )}
            {/* Empty area drop zone — drops to root */}
            {draggingPath && (
              <div
                className={`flex-1 min-h-8 transition-colors ${dropTargetPath === "" ? "bg-primary/10" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setDropTargetPath(""); }}
                onDragEnter={(e) => { e.preventDefault(); setDropTargetPath(""); }}
                onDragLeave={() => { setDropTargetPath((p) => p === "" ? null : p); }}
                onDrop={(e) => { e.preventDefault(); handleTreeDrop(""); }}
              />
            )}
          </div>
        </aside>

        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {rightPane === "file" && openDocument ? (
            <FileView
              document={openDocument}
              editContent={editContent}
              setEditContent={updateEditContent}
              loading={editLoading}
              saving={saving}
              dirty={editorDirty}
              onSave={handleSave}
              onClose={closeFileView}
              onDelete={(path) => setDeleteTarget({ type: "file", value: path })}
              onMove={(path) => setMovingPath(path)}
              onToggleEnabled={handleToggleEnabled}
            />
          ) : null}
        </div>
      </div>
      </>
      )}

      {movingPath && (
        <MoveModal
          sourcePath={movingPath}
          allDocuments={documents}
          serverDirs={serverDirs}
          onMove={handleMove}
          onClose={() => setMovingPath(null)}
        />
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={deleteTarget?.type === "dir" ? "刪除資料夾" : "刪除文件"}
        message={deleteMessage}
        confirmLabel="刪除"
        danger
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />

      {showNoteModal && (
        <NoteModal
          noteTitle={noteTitle}
          setNoteTitle={setNoteTitle}
          noteContent={noteContent}
          setNoteContent={setNoteContent}
          creating={creatingNote}
          onClose={closeNoteModal}
          onCreate={handleCreateNote}
        />
      )}
    </div>
  );
}
