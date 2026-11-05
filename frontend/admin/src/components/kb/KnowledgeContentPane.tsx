import { useMemo, type ReactNode } from "react";

import type {
  KnowledgeDocument,
  KnowledgeDocumentSummary,
  KnowledgeLanguage,
  KnowledgeNoteFormat,
} from "../../api";
import type { QaNode } from "../../hooks/useQaNodes";
import type { Status } from "../../hooks/useStatusState";
import FileView from "./FileView";
import {
  findNodeReferencingSource,
  findQaNode,
  getQaNodeAncestors,
  type RightPane,
} from "./helpers";
import NoteComposer from "./NoteComposer";
import MergedCsvPane, { type QaFocusRequest } from "./qa/MergedCsvPane";

interface KnowledgeContentPaneProps {
  /** 沒有選任何東西時顯示的「新增資料」畫面。 */
  home: ReactNode;
  /** 上次看的文件還原完才知道要不要顯示首頁，先不要閃一下。 */
  contentReady: boolean;
  showNoteComposer: boolean;
  noteComposerFormat: KnowledgeNoteFormat;
  creatingNote: boolean;
  onCloseNoteComposer: () => void;
  onCreateNote: (title: string, content: string, format: KnowledgeNoteFormat) => void;
  selectedQaNodeId: string | null;
  selectedQaNodeLabel?: string;
  mergedRefreshKey: number;
  qaFocusRequest: QaFocusRequest | null;
  onQaStatus: (status: Status) => void;
  onQaMutationSuccess: () => void;
  nodesTree: QaNode[];
  /** 「前往快速問答」：FileView 已經問過要不要捨棄，這裡不能再問一次。 */
  onOpenQaNode: (nodeId: string) => void;
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
}

export default function KnowledgeContentPane({
  home,
  contentReady,
  showNoteComposer,
  noteComposerFormat,
  creatingNote,
  onCloseNoteComposer,
  onCreateNote,
  selectedQaNodeId,
  selectedQaNodeLabel,
  mergedRefreshKey,
  qaFocusRequest,
  onQaStatus,
  onQaMutationSuccess,
  nodesTree,
  onOpenQaNode,
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
}: KnowledgeContentPaneProps) {
  const attachedNodeForOpenDocument = useMemo(() => {
    if (!openDocument || openDocument.source_type !== "qa") return null;
    return findNodeReferencingSource(nodesTree, openDocument.path) ?? null;
  }, [openDocument, nodesTree]);

  const selectedQaNode = selectedQaNodeId ? findQaNode(nodesTree, selectedQaNodeId) : undefined;
  const qaAncestors = useMemo(() => {
    if (!selectedQaNodeId) return [];
    return (getQaNodeAncestors(nodesTree, selectedQaNodeId) ?? [])
      .flatMap((nodeId) => findQaNode(nodesTree, nodeId) ?? []);
  }, [nodesTree, selectedQaNodeId]);

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      {showNoteComposer ? (
        <NoteComposer
          creating={creatingNote}
          initialFormat={noteComposerFormat}
          onClose={onCloseNoteComposer}
          onCreate={onCreateNote}
        />
      ) : selectedQaNodeId ? (
        <main className="min-w-0 flex-1 overflow-auto md:p-4">
          <MergedCsvPane
            nodeId={selectedQaNodeId}
            nodeLabel={selectedQaNodeLabel}
            parentLabels={qaAncestors.map((node) => node.label)}
            nodeHidden={Boolean(selectedQaNode?.hidden) || qaAncestors.some((node) => node.hidden)}
            childCategoryCount={selectedQaNode?.children?.length ?? 0}
            refreshKey={mergedRefreshKey}
            focusQuestion={qaFocusRequest}
            onStatus={onQaStatus}
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
              ? () => onOpenQaNode(attachedNodeForOpenDocument.node_id)
              : undefined
          }
          renormalizing={renormalizing}
        />
      ) : rightPane === "file" || !contentReady ? (
        <div className="flex flex-1 items-center justify-center text-sm text-content-subtle">
          <span aria-hidden="true" className="material-symbols-outlined mr-1 animate-spin text-[1rem]">refresh</span>
          載入中…
        </div>
      ) : (
        home
      )}
    </div>
  );
}
