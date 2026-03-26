import ConfirmModal from "../components/ConfirmModal";
import StatusAlert from "../components/StatusAlert";
import FileView from "../components/kb/FileView";
import FolderView from "../components/kb/FolderView";
import MoveModal from "../components/kb/MoveModal";
import NoteModal from "../components/kb/NoteModal";
import SourcePanel from "../components/kb/SourcePanel";
import TreeView from "../components/kb/TreeView";
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
    expandedDirs,
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
    tree,
    currentDir,
    indexedCount,
    folderSubdirs,
    filteredFiles,
    setStatus,
    setSearch,
    setSelectedPath,
    setExpandedDirs,
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
    openFile,
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

  const openFileHandler = (path: string) => {
    setSelectedPath(path);
    openFile(path);
  };

  return (
    <div
      className="h-full flex flex-col overflow-hidden bg-background"
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragOver && (
        <div className="fixed inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <div className="bg-slate-900 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">upload_file</span>
            <span className="text-xl font-bold text-white">拖放檔案以上傳到 {currentDir}</span>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/60 shrink-0">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary text-[24px]">school</span>
          <h1 className="text-lg font-bold text-white">知識庫</h1>
          <span className="text-xs text-slate-500">{documents.length} 文件 · {indexedCount} 已索引</span>
        </div>
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
      </div>

      {status && (
        <div className="px-4 pt-2 shrink-0">
          <StatusAlert type={status.type} message={status.message} onDismiss={() => setStatus(null)} />
        </div>
      )}

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
        <aside className="w-64 xl:w-72 shrink-0 border-r border-slate-800/60 flex flex-col bg-slate-950/30 overflow-hidden">
          <div className="px-3 py-2.5 border-b border-slate-800/40 flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">檔案樹</span>
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

          {showNewFolder && (
            <form onSubmit={handleCreateFolderSubmit} className="flex items-center gap-1 px-3 py-2 border-b border-slate-800/40 bg-primary/5">
              <input
                autoFocus
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="資料夾名稱"
                className="bg-transparent text-xs text-white placeholder:text-slate-500 outline-none flex-1 min-w-0"
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    cancelCreateFolder();
                  }
                }}
              />
              <button type="submit" disabled={!newFolderName.trim()} className="p-0.5 text-primary disabled:opacity-30">
                <span className="material-symbols-outlined text-[16px]">check</span>
              </button>
              <button type="button" onClick={cancelCreateFolder} className="p-0.5 text-slate-500 hover:text-slate-300">
                <span className="material-symbols-outlined text-[16px]">close</span>
              </button>
            </form>
          )}

          <div className="flex-1 overflow-y-auto overflow-x-hidden py-1">
            {loading && !documents.length ? (
              <div className="flex items-center justify-center py-10 text-slate-500 text-xs">
                <span className="material-symbols-outlined animate-spin mr-1 text-[16px]">refresh</span> 載入中...
              </div>
            ) : (
              <TreeView
                node={tree}
                depth={0}
                selectedPath={selectedPath}
                expandedDirs={expandedDirs}
                onSelect={handleTreeSelect}
                onToggle={toggleExpand}
                onDelete={(node) =>
                  setDeleteTarget({ type: node.type === "folder" ? "dir" : "file", value: node.path })
                }
              />
            )}
          </div>
        </aside>

        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {rightPane === "folder" ? (
            <FolderView
              dir={currentDir}
              files={filteredFiles}
              subdirs={folderSubdirs}
              search={search}
              setSearch={setSearch}
              loading={loading}
              onSelectFile={openFileHandler}
              onSelectDir={(dir) => {
                setSelectedPath(dir);
                setExpandedDirs((prev) => new Set([...prev, dir]));
              }}
              onDelete={(path) => setDeleteTarget({ type: "file", value: path })}
              onDeleteDir={(dir) => setDeleteTarget({ type: "dir", value: dir })}
              onEdit={openFileHandler}
              onMove={(path) => setMovingPath(path)}
              onToggleEnabled={handleToggleEnabled}
            />
          ) : (
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
          )}
        </div>
      </div>

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
        message={
          deleteTarget?.type === "dir"
            ? `確定要刪除資料夾 ${deleteTarget.value} 嗎？`
            : `確定要刪除 ${deleteTarget?.value} 嗎？`
        }
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
