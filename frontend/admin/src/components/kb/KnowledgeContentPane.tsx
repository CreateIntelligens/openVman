import { useMemo, type ReactNode } from "react";

import type {
  KnowledgeDocument,
  KnowledgeDocumentSummary,
  KnowledgeLanguage,
  KnowledgeNoteFormat,
} from "../../api";
import type { QaNode } from "../../hooks/useQaNodes";
import FileView from "./FileView";
import {
  findNodeReferencingSource,
  type RightPane,
} from "./helpers";
import NoteComposer from "./NoteComposer";

interface KnowledgeContentPaneProps {
  vendor?: boolean;
  documentLabels?: ReadonlyMap<string, string>;
  questionBank: ReactNode;
  showHome: boolean;
  home: ReactNode;
  /** 上次看的文件還原完才知道要不要顯示首頁，先不要閃一下。 */
  contentReady: boolean;
  showNoteComposer: boolean;
  noteComposerFormat: KnowledgeNoteFormat;
  creatingNote: boolean;
  onCloseNoteComposer: () => void;
  onCreateNote: (title: string, content: string, format: KnowledgeNoteFormat) => void;
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
  /** 沒給就不顯示「AI 整理排版」：帳號沒有開放這個權限。 */
  onRenormalize?: (path: string) => void;
  renormalizing: boolean;
}

export default function KnowledgeContentPane({
  vendor = false,
  documentLabels,
  home,
  questionBank,
  showHome,
  contentReady,
  showNoteComposer,
  noteComposerFormat,
  creatingNote,
  onCloseNoteComposer,
  onCreateNote,
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

  return (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      {showNoteComposer ? (
        <NoteComposer
          vendor={vendor}
          creating={creatingNote}
          initialFormat={noteComposerFormat}
          onClose={onCloseNoteComposer}
          onCreate={onCreateNote}
        />
      ) : rightPane === "file" && openDocument ? (
        <FileView
          vendor={vendor}
          documentLabels={documentLabels}
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
      ) : showHome ? (
        home
      ) : (
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto xl:overflow-hidden">
          <div className="flex min-w-0 flex-col xl:h-full xl:flex-row">{questionBank}</div>
        </div>
      )}
    </div>
  );
}
