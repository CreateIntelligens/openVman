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
  "createNode" | "updateNode" | "deleteNode"
>;

interface UseQaNodeModalsOptions extends QaNodeActions {
  nodesTree: QaNode[];
  setSelectedQaNodeId: Dispatch<SetStateAction<string | null>>;
}

export function useQaNodeModals({
  nodesTree,
  createNode,
  updateNode,
  deleteNode,
  setSelectedQaNodeId,
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

  const closeQaNodeDialog = useCallback(() => {
    setQaNodeDialog(null);
  }, []);

  const handleCreateQaNodeSubmit = useCallback(
    (values: Record<string, string>) => {
      const parentIds =
        qaNodeDialog?.type === "add-child" ? [qaNodeDialog.parentNodeId] : [];
      const nodeId = values.node_id || `node_${Date.now()}`;
      void createNode(nodeId, values.label, parentIds, [], 1.0, false);
      closeQaNodeDialog();
    },
    [closeQaNodeDialog, createNode, qaNodeDialog],
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
      return res;
    },
    [deleteNode],
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
    closeQaNodeDialog,
    handleCreateQaNodeSubmit,
    handleRenameQaNodeSubmit,
    handleToggleQaNodeHidden,
    handleDeleteQaNodeConfirm,
  };
}
