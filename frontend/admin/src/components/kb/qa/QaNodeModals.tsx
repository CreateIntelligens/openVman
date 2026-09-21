import type { QaNode } from "../../../hooks/useQaNodes";
import PromptModal from "../../PromptModal";
import ConfirmModal from "../../ConfirmModal";

export type QaNodeDialog =
  | { type: "add-root" }
  | { type: "add-child"; parentNodeId: string; parentLabel: string }
  | { type: "rename"; node: QaNode }
  | { type: "delete"; node: QaNode };

interface QaNodeModalsProps {
  dialog: QaNodeDialog | null;
  onClose: () => void;
  onCreateSubmit: (values: Record<string, string>) => void;
  onRenameSubmit: (values: Record<string, string>) => void;
  onDeleteConfirm: () => void;
}

export default function QaNodeModals({
  dialog,
  onClose,
  onCreateSubmit,
  onRenameSubmit,
  onDeleteConfirm,
}: QaNodeModalsProps) {
  return (
    <>
      <PromptModal
        open={dialog?.type === "add-root" || dialog?.type === "add-child"}
        title={
          dialog?.type === "add-child"
            ? `在「${dialog.parentLabel}」下新增子節點`
            : "新增快速問答節點"
        }
        fields={[
          { key: "label", label: "節點名稱", placeholder: "請輸入名稱", required: true },
          {
            key: "node_id",
            label: "唯一識別碼",
            placeholder: "留空自動生成",
            hint: "限英文/數字/底線；留空自動生成",
          },
        ]}
        submitLabel="新增"
        onSubmit={onCreateSubmit}
        onCancel={onClose}
      />

      <PromptModal
        open={dialog?.type === "rename"}
        title="修改快速問答節點名稱"
        fields={[
          {
            key: "label",
            label: "節點名稱",
            initialValue: dialog?.type === "rename" ? dialog.node.label : "",
            required: true,
          },
        ]}
        submitLabel="儲存"
        onSubmit={onRenameSubmit}
        onCancel={onClose}
      />

      <ConfirmModal
        open={dialog?.type === "delete"}
        title="刪除快速問答節點"
        message={
          dialog?.type === "delete"
            ? `確定要刪除節點「${dialog.node.label}」嗎？節點的問答內容檔案將一併刪除。`
            : ""
        }
        confirmLabel="刪除"
        danger
        onConfirm={onDeleteConfirm}
        onCancel={onClose}
      />
    </>
  );
}
