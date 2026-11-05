import type { QaNode } from "../../../hooks/useQaNodes";
import PromptModal from "../../PromptModal";
import ConfirmModal from "../../ConfirmModal";
import {
  isLanguageCategory,
  LANGUAGE_CATEGORY_RENAME_WARNING,
} from "./languageCategories";
import MoveQaNodeModal from "./MoveQaNodeModal";

export type QaNodeDialog =
  | { type: "add-root" }
  | { type: "add-child"; parentNodeId: string; parentLabel: string }
  | { type: "rename"; node: QaNode }
  | { type: "move"; node: QaNode }
  | { type: "delete"; node: QaNode };

interface QaNodeModalsProps {
  dialog: QaNodeDialog | null;
  nodesTree: QaNode[];
  onClose: () => void;
  onCreateSubmit: (values: Record<string, string>) => void;
  onRenameSubmit: (values: Record<string, string>) => void;
  onMoveConfirm: (parentId: string | null) => void | Promise<void>;
  onDeleteConfirm: () => void;
}

function deleteMessage(node: QaNode): string {
  const childCount = node.children?.length ?? 0;
  const childNote = childCount > 0
    ? `底下的 ${childCount} 個子分類不會被刪除，會移到最上層。`
    : "";
  return `確定要刪除分類「${node.label}」嗎？訪客的選單上不會再出現這個分類和它的問題。問題和答案會留在文件裡，AI 回答時還是會用；之後想放回選單，把文件拖進分類就好。${childNote}`;
}

export default function QaNodeModals({
  dialog,
  nodesTree,
  onClose,
  onCreateSubmit,
  onRenameSubmit,
  onMoveConfirm,
  onDeleteConfirm,
}: QaNodeModalsProps) {
  return (
    <>
      <PromptModal
        open={dialog?.type === "add-root" || dialog?.type === "add-child"}
        title={
          dialog?.type === "add-child"
            ? `在「${dialog.parentLabel}」底下新增子分類`
            : "新增分類"
        }
        fields={[
          { key: "label", label: "分類名稱", placeholder: "例如：停車與交通", required: true },
        ]}
        submitLabel="新增"
        onSubmit={onCreateSubmit}
        onCancel={onClose}
      />

      <PromptModal
        open={dialog?.type === "rename"}
        title="重新命名分類"
        fields={[
          {
            key: "label",
            label: "分類名稱",
            initialValue: dialog?.type === "rename" ? dialog.node.label : "",
            required: true,
            hint: dialog?.type === "rename" && isLanguageCategory(nodesTree, dialog.node.node_id)
              ? LANGUAGE_CATEGORY_RENAME_WARNING
              : undefined,
          },
        ]}
        submitLabel="儲存"
        onSubmit={onRenameSubmit}
        onCancel={onClose}
      />

      {dialog?.type === "move" && (
        <MoveQaNodeModal
          node={dialog.node}
          nodesTree={nodesTree}
          onConfirm={onMoveConfirm}
          onClose={onClose}
        />
      )}

      <ConfirmModal
        open={dialog?.type === "delete"}
        title="刪除分類"
        message={dialog?.type === "delete" ? deleteMessage(dialog.node) : ""}
        confirmLabel="刪除"
        danger
        onConfirm={onDeleteConfirm}
        onCancel={onClose}
      />
    </>
  );
}
