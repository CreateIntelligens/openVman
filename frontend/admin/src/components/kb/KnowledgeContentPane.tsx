import { useMemo, type MouseEvent as ReactMouseEvent } from "react";

import type {
  KnowledgeDocument,
  KnowledgeDocumentSummary,
  KnowledgeLanguage,
  KnowledgeNoteFormat,
} from "../../api";
import type { QaNode } from "../../hooks/useQaNodes";
import FileView from "./FileView";
import { findNodeReferencingSource, type RightPane } from "./helpers";
import NoteComposer from "./NoteComposer";
import MergedCsvPane from "./qa/MergedCsvPane";

interface KnowledgeContentPaneProps {
  showNoteComposer: boolean;
  creatingNote: boolean;
  onCloseNoteComposer: () => void;
  onCreateNote: (title: string, content: string, format: KnowledgeNoteFormat) => void;
  selectedQaNodeId: string | null;
  selectedQaNodeLabel?: string;
  mergedRefreshKey: number;
  onQaMutationSuccess: () => void;
  nodesTree: QaNode[];
  onSelectQaNode: (nodeId: string) => void;
  rightPane: RightPane;
  openDocument: KnowledgeDocument | null;
  editContent: string;
  onEditContentChange: (content: string) => void;
  editLoading: boolean;
  saving: boolean;
  editorDirty: boolean;
  onSave: () => void;
  onCloseFileView: () => void;
  onDeleteFile: (path: string) => void;
  onMoveFile: (path: string) => void;
  onToggleEnabled: (doc: KnowledgeDocumentSummary) => void;
  onChangeLanguage: (doc: KnowledgeDocumentSummary, language: KnowledgeLanguage | "auto") => void;
  onRenormalize: (path: string) => void;
  renormalizing: boolean;
  onOpenMobileTree: (event: ReactMouseEvent<HTMLButtonElement>) => void;
}

export default function KnowledgeContentPane({
  showNoteComposer,
  creatingNote,
  onCloseNoteComposer,
  onCreateNote,
  selectedQaNodeId,
  selectedQaNodeLabel,
  mergedRefreshKey,
  onQaMutationSuccess,
  nodesTree,
  onSelectQaNode,
  rightPane,
  openDocument,
  editContent,
  onEditContentChange,
  editLoading,
  saving,
  editorDirty,
  onSave,
  onCloseFileView,
  onDeleteFile,
  onMoveFile,
  onToggleEnabled,
  onChangeLanguage,
  onRenormalize,
  renormalizing,
  onOpenMobileTree,
}: KnowledgeContentPaneProps) {
  const attachedNodeForOpenDocument = useMemo(() => {
    if (!openDocument || openDocument.source_type !== "qa") return null;
    return findNodeReferencingSource(nodesTree, openDocument.path) ?? null;
  }, [openDocument, nodesTree]);

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      {showNoteComposer ? (
        <NoteComposer
          creating={creatingNote}
          onClose={onCloseNoteComposer}
          onCreate={onCreateNote}
        />
      ) : selectedQaNodeId ? (
        <main className="flex-1 min-w-0 p-4 overflow-auto">
          <MergedCsvPane
            nodeId={selectedQaNodeId}
            nodeLabel={selectedQaNodeLabel}
            refreshKey={mergedRefreshKey}
            onSuccess={onQaMutationSuccess}
          />
        </main>
      ) : rightPane === "file" && openDocument ? (
        <FileView
          document={openDocument}
          editContent={editContent}
          setEditContent={onEditContentChange}
          loading={editLoading}
          saving={saving}
          dirty={editorDirty}
          onSave={onSave}
          onClose={onCloseFileView}
          onDelete={onDeleteFile}
          onMove={onMoveFile}
          onToggleEnabled={onToggleEnabled}
          onChangeLanguage={onChangeLanguage}
          onRenormalize={onRenormalize}
          onOpenQaTree={
            attachedNodeForOpenDocument
              ? () => onSelectQaNode(attachedNodeForOpenDocument.node_id)
              : undefined
          }
          renormalizing={renormalizing}
        />
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-sm text-content-muted">
          <span className="material-symbols-outlined text-3xl text-content-subtle">
            description
          </span>
          <p>從檔案樹選擇文件或快速問答節點</p>
          <button
            type="button"
            onClick={onOpenMobileTree}
            className="btn btn-ghost md:hidden"
          >
            開啟檔案樹
          </button>
        </div>
      )}
    </div>
  );
}
