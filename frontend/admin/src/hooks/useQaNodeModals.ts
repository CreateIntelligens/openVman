import {
  useCallback,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { findQaNode } from "../components/kb/helpers";
import type { QaNodeDialog } from "../components/kb/qa/QaNodeModals";
import type { QaNode, useQaNodes } from "./useQaNodes";

type QaNodeActions = Pick<
  ReturnType<typeof useQaNodes>,
  "createNode" | "updateNode" | "deleteNode" | "moveNode"
>;

interface UseQaNodeModalsOptions extends QaNodeActions {
  nodesTree: QaNode[];
  setSelectedQaNodeId: Dispatch<SetStateAction<string | null>>;
  fetchQaTree: () => Promise<unknown>;
  loadDocuments: () => Promise<void>;
  /** 分類換了上層之後呼叫；parentId 是 null 代表移到最上層。 */
  onQaNodeMoved: (parentId: string | null) => void;
  /** 讓某個分類的內容在樹上看得到；null 代表快速問答最上層。 */
  onRevealQaNode: (nodeId: string | null) => void;
}

export function useQaNodeModals({
  nodesTree,
  createNode,
  updateNode,
  deleteNode,
  moveNode,
  setSelectedQaNodeId,
  fetchQaTree,
  loadDocuments,
  onQaNodeMoved,
  onRevealQaNode,
}: UseQaNodeModalsOptions) {
  const [qaNodeDialog, setQaNodeDialog] = useState<QaNodeDialog | null>(null);
  const [orderModalOpen, setOrderModalOpen] = useState(false);
  const [orderModalParentNode, setOrderModalParentNode] = useState<QaNode | null>(null);

  const handleOpenOrderModal = useCallback(
    (parentNodeId: string | null) => {
      if (parentNodeId === null) {
        setOrderModalParentNode(null);
      } else {
        const node = findQaNode(nodesTree, parentNodeId);
        if (node) {
          setOrderModalParentNode(node);
        } else {
          return;
        }
      }
      setOrderModalOpen(true);
    },
    [nodesTree],
  );

  const closeOrderModal = useCallback(() => {
    setOrderModalOpen(false);
    setOrderModalParentNode(null);
  }, []);

  const openCreateQaNodeDialog = useCallback(
    (parentNodeId: string | null) => {
      if (!parentNodeId) {
        setQaNodeDialog({ type: "add-root" });
        return;
      }

      const parent = findQaNode(nodesTree, parentNodeId);
      if (!parent) return;
      setQaNodeDialog({
        type: "add-child",
        parentNodeId,
        parentLabel: parent.label,
      });
    },
    [nodesTree],
  );

  const openRenameQaNodeDialog = useCallback(
    (nodeId: string) => {
      const node = findQaNode(nodesTree, nodeId);
      if (!node) return;
      setQaNodeDialog({ type: "rename", node });
    },
    [nodesTree],
  );

  const openDeleteQaNodeDialog = useCallback(
    (nodeId: string) => {
      const node = findQaNode(nodesTree, nodeId);
      if (!node) return;
      setQaNodeDialog({ type: "delete", node });
    },
    [nodesTree],
  );

  const openMoveQaNodeDialog = useCallback(
    (nodeId: string) => {
      const node = findQaNode(nodesTree, nodeId);
      if (!node) return;
      setQaNodeDialog({ type: "move", node });
    },
    [nodesTree],
  );

  const closeQaNodeDialog = useCallback(() => {
    setQaNodeDialog(null);
  }, []);

  // 失敗時讓錯誤往外丟：對話框留著並寫出原因，使用者不用重選一次。
  const handleMoveQaNodeConfirm = useCallback(
    async (parentId: string | null) => {
      if (qaNodeDialog?.type !== "move") return;
      await moveNode(qaNodeDialog.node.node_id, parentId ? [parentId] : []);
      await fetchQaTree();
      onQaNodeMoved(parentId);
      closeQaNodeDialog();
    },
    [closeQaNodeDialog, fetchQaTree, moveNode, onQaNodeMoved, qaNodeDialog],
  );

  const handleCreateQaNodeSubmit = useCallback(
    (values: Record<string, string>) => {
      const parentId =
        qaNodeDialog?.type === "add-child" ? qaNodeDialog.parentNodeId : null;
      void createNode(
        `node_${Date.now()}`,
        values.label,
        parentId ? [parentId] : [],
        [],
        1.0,
        false,
      );
      // 上層收合著的話新分類看不到，使用者會以為沒有新增成功。
      onRevealQaNode(parentId);
      closeQaNodeDialog();
    },
    [closeQaNodeDialog, createNode, onRevealQaNode, qaNodeDialog],
  );

  const handleRenameQaNodeSubmit = useCallback(
    (values: Record<string, string>) => {
      if (
        qaNodeDialog?.type === "rename" &&
        values.label !== qaNodeDialog.node.label
      ) {
        void updateNode(qaNodeDialog.node.node_id, { label: values.label });
      }
      closeQaNodeDialog();
    },
    [closeQaNodeDialog, qaNodeDialog, updateNode],
  );

  const handleToggleQaNodeHidden = useCallback(
    (nodeId: string, hidden: boolean) => {
      void updateNode(nodeId, { hidden });
    },
    [updateNode],
  );

  const handleDeleteQaNode = useCallback(
    async (id: string) => {
      const res = await deleteNode(id);
      setSelectedQaNodeId((current) => (current === id ? null : current));
      // 後端會一併刪掉分類專屬的來源文件，文件那一段也要跟著更新。
      await loadDocuments();
      return res;
    },
    [deleteNode, loadDocuments, setSelectedQaNodeId],
  );

  const handleDeleteQaNodeConfirm = useCallback(() => {
    if (qaNodeDialog?.type === "delete") {
      void handleDeleteQaNode(qaNodeDialog.node.node_id);
    }
    closeQaNodeDialog();
  }, [closeQaNodeDialog, handleDeleteQaNode, qaNodeDialog]);

  return {
    qaNodeDialog,
    orderModalOpen,
    orderModalParentNode,
    handleOpenOrderModal,
    closeOrderModal,
    openCreateQaNodeDialog,
    openRenameQaNodeDialog,
    openDeleteQaNodeDialog,
    openMoveQaNodeDialog,
    closeQaNodeDialog,
    handleCreateQaNodeSubmit,
    handleRenameQaNodeSubmit,
    handleMoveQaNodeConfirm,
    handleToggleQaNodeHidden,
    handleDeleteQaNodeConfirm,
  };
}
