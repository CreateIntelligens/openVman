import { useMemo, type ComponentProps } from "react";

import type {
  KnowledgeDocumentSummary,
  KnowledgeNormalizationPreviewResponse,
} from "../../api";
import type { QaNode } from "../../hooks/useQaNodes";
import ConfirmModal from "../ConfirmModal";
import { isUploadDerivedKnowledgeFile, type DeleteTarget } from "./helpers";
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
  const isUploadDerived =
    !!deleteTargetDocument && isUploadDerivedKnowledgeFile(deleteTargetDocument);
  const isQaAttachedTarget =
    deleteTargetDocument?.source_type === "qa" &&
    deleteTargetDocument?.qa_attached === true;
  const deleteMessage =
    deleteTarget?.type === "dir"
      ? `確定要刪除資料夾 ${deleteTarget.value} 嗎？目錄內仍有檔案時不會刪除。`
      : isQaAttachedTarget
      ? `確定要刪除 ${deleteTarget?.value} 嗎？快速問答樹上對應的節點與題目會一併移除。`
      : isUploadDerived
      ? `確定要刪除 ${deleteTarget?.value} 嗎？這只會移除知識文件與索引；原始上傳檔仍保留在 raw/。`
      : `確定要刪除 ${deleteTarget?.value} 嗎？`;

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
