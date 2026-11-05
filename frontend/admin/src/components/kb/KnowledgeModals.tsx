import { useMemo, type ComponentProps } from "react";

import type {
  KnowledgeDocumentSummary,
  KnowledgeNormalizationPreviewResponse,
} from "../../api";
import type { QaNode } from "../../hooks/useQaNodes";
import ConfirmModal from "../ConfirmModal";
import {
  displayDocumentPath,
  fileNameOf,
  hasOriginalBackup,
  type DeleteTarget,
} from "./helpers";
import MoveModal from "./MoveModal";
import NormalizationPreviewModal from "./NormalizationPreviewModal";
import VisibilityOrderModal from "./qa/VisibilityOrderModal";

type OrderModalProps = ComponentProps<typeof VisibilityOrderModal>;

interface KnowledgeModalsProps {
  documents: KnowledgeDocumentSummary[];
  serverDirs: string[];
  movingPath: string | null;
  onMove: (sourcePath: string, targetDir: string) => void;
  onCloseMove: () => void;
  deleteTarget: DeleteTarget;
  onDeleteConfirm: () => void;
  onCancelDelete: () => void;
  normalizationPreview: KnowledgeNormalizationPreviewResponse | null;
  renormalizing: boolean;
  onApplyNormalizationPreview: () => void;
  onCloseNormalizationPreview: () => void;
  orderModalOpen: boolean;
  orderModalParentNode: QaNode | null;
  onCloseOrderModal: () => void;
  nodesTree: QaNode[];
  onUpdateNode: OrderModalProps["onUpdateNode"];
  onReorderNode: OrderModalProps["onReorderNode"];
  onRefreshQaTree: OrderModalProps["onRefresh"];
}

export default function KnowledgeModals({
  documents,
  serverDirs,
  movingPath,
  onMove,
  onCloseMove,
  deleteTarget,
  onDeleteConfirm,
  onCancelDelete,
  normalizationPreview,
  renormalizing,
  onApplyNormalizationPreview,
  onCloseNormalizationPreview,
  orderModalOpen,
  orderModalParentNode,
  onCloseOrderModal,
  nodesTree,
  onUpdateNode,
  onReorderNode,
  onRefreshQaTree,
}: KnowledgeModalsProps) {
  const deleteTargetDocument = useMemo(
    () =>
      deleteTarget?.type === "file"
        ? documents.find((document) => document.path === deleteTarget.value) ?? null
        : null,
    [deleteTarget, documents],
  );
  const keepsOriginal =
    !!deleteTargetDocument && hasOriginalBackup(deleteTargetDocument);
  const isQaAttachedTarget =
    deleteTargetDocument?.source_type === "qa" &&
    deleteTargetDocument?.qa_attached === true;
  const deleteFileName = deleteTarget ? fileNameOf(deleteTarget.value) : "";
  const deleteMessage =
    deleteTarget?.type === "dir"
      ? `確定要刪除資料夾「${displayDocumentPath(deleteTarget.value)}」嗎？資料夾裡還有檔案時不會刪除。`
      : isQaAttachedTarget
      ? `確定要刪除「${deleteFileName}」嗎？快速問答裡對應的分類和題目也會一起刪除。`
      : keepsOriginal
      ? `確定要刪除「${deleteFileName}」嗎？這只會把內容從知識庫移除，原始上傳檔還留在系統備份裡。`
      : `確定要刪除「${deleteFileName}」嗎？`;

  return (
    <>
      {movingPath && (
        <MoveModal
          sourcePaths={[movingPath]}
          allDocuments={documents}
          serverDirs={serverDirs}
          onMove={(targetDir) => onMove(movingPath, targetDir)}
          onClose={onCloseMove}
        />
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={deleteTarget?.type === "dir" ? "刪除資料夾" : "刪除文件"}
        message={deleteMessage}
        confirmLabel="刪除"
        danger
        onConfirm={onDeleteConfirm}
        onCancel={onCancelDelete}
      />

      {normalizationPreview && (
        <NormalizationPreviewModal
          path={normalizationPreview.path}
          content={normalizationPreview.content}
          applying={renormalizing}
          onApply={onApplyNormalizationPreview}
          onClose={onCloseNormalizationPreview}
        />
      )}

      {orderModalOpen && (
        <VisibilityOrderModal
          isOpen={orderModalOpen}
          onClose={onCloseOrderModal}
          parentNode={orderModalParentNode}
          nodesTree={nodesTree}
          onUpdateNode={onUpdateNode}
          onReorderNode={onReorderNode}
          onRefresh={onRefreshQaTree}
        />
      )}
    </>
  );
}
