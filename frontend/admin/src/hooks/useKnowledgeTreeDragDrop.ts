import {
  useCallback,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { QaDropPosition, TreeNode } from "../components/kb/helpers";
import {
  findQaNode,
  getQaNodeParentId,
  isQaNodeDescendant,
  parseQaEntryDragPath,
  parseQaNodeDragPath,
  qaEntryDragPath,
  qaNodeDragPath,
  QUICK_QA_TREE_PATH,
} from "../components/kb/helpers";
import type { QaNode, useQaNodes } from "./useQaNodes";

type QaTreeActions = Pick<
  ReturnType<typeof useQaNodes>,
  | "moveNode"
  | "reorderNode"
  | "fetchMergedQa"
  | "saveMergedQa"
  | "adoptSource"
  | "ingestSource"
>;

interface UseKnowledgeTreeDragDropOptions extends QaTreeActions {
  nodesTree: QaNode[];
  selectedQaNodeId: string | null;
  fetchQaTree: () => Promise<unknown>;
  loadDocuments: () => Promise<void>;
  handleMove: (sourcePath: string, targetDir: string) => Promise<void>;
  setMergedRefreshKey: Dispatch<SetStateAction<number>>;
  /** 分類換了上層之後呼叫；parentId 是 null 代表移到最上層。 */
  onQaNodeMoved?: (parentId: string | null) => void;
}

export function useKnowledgeTreeDragDrop({
  nodesTree,
  selectedQaNodeId,
  moveNode,
  reorderNode,
  fetchMergedQa,
  saveMergedQa,
  adoptSource,
  ingestSource,
  fetchQaTree,
  loadDocuments,
  handleMove,
  setMergedRefreshKey,
  onQaNodeMoved,
}: UseKnowledgeTreeDragDropOptions) {
  const [draggingPath, setDraggingPath] = useState<string | null>(null);
  const [dropTargetPath, setDropTargetPath] = useState<string | null>(null);
  const [dropPosition, setDropPosition] = useState<QaDropPosition | null>(null);

  const setDropTarget = useCallback(
    (path: string | null, position: QaDropPosition | null = null) => {
      setDropTargetPath(path);
      setDropPosition(position);
    },
    [],
  );

  const canDropQaNode = useCallback(
    (draggedPath: string, targetPath: string, position?: QaDropPosition) => {
      const draggedNodeId = parseQaNodeDragPath(draggedPath);
      if (!draggedNodeId) return false;
      // 已經在最上層：放回「快速問答」沒有變化，不要顯示成可以放。
      if (targetPath === QUICK_QA_TREE_PATH) {
        return getQaNodeParentId(nodesTree, draggedNodeId) !== null;
      }
      const targetNodeId = parseQaNodeDragPath(targetPath);
      if (!targetNodeId) return false;
      if (draggedNodeId === targetNodeId) return false;

      const draggedNode = findQaNode(nodesTree, draggedNodeId);
      const targetNode = findQaNode(nodesTree, targetNodeId);
      if (!draggedNode || !targetNode) return false;

      // 三種放法都不能進自己的子孫：排在子孫旁邊等於放進子孫的上層。
      if (isQaNodeDescendant(draggedNode, targetNodeId)) return false;
      // 已經在這個分類底下：放進去沒有變化，不要顯示成可以放。
      if (position === "into" && draggedNode.parent_ids?.includes(targetNodeId)) {
        return false;
      }
      return true;
    },
    [nodesTree],
  );

  const canDropQaEntry = useCallback((draggedPath: string, targetPath: string) => {
    const draggedEntry = parseQaEntryDragPath(draggedPath);
    const targetEntry = parseQaEntryDragPath(targetPath);
    if (!draggedEntry || !targetEntry) return false;
    if (draggedEntry.nodeId !== targetEntry.nodeId) return false;
    return draggedEntry.question !== targetEntry.question;
  }, []);

  const sourceDragDir = useMemo(() => {
    if (
      !draggingPath ||
      parseQaNodeDragPath(draggingPath) ||
      parseQaEntryDragPath(draggingPath)
    ) {
      return "";
    }
    return draggingPath.split("/").slice(0, -1).join("/");
  }, [draggingPath]);

  const handleTreeDragStart = useCallback((node: TreeNode) => {
    if (node.treeKind === "qa-node" && node.qaNodeId) {
      setDraggingPath(qaNodeDragPath(node.qaNodeId));
      return;
    }
    if (node.treeKind === "qa-entry" && node.qaNodeId) {
      setDraggingPath(
        qaEntryDragPath(node.qaNodeId, node.qaEntryQuestion ?? node.name),
      );
      return;
    }
    setDraggingPath(node.path);
  }, []);

  const handleTreeDragEnd = useCallback(() => {
    setDraggingPath(null);
    setDropTarget(null);
  }, [setDropTarget]);

  const dropQaNodeOntoNode = useCallback(
    async (draggedId: string, targetId: string, position: QaDropPosition) => {
      const draggedNode = findQaNode(nodesTree, draggedId);
      const targetNode = findQaNode(nodesTree, targetId);
      if (!draggedNode || !targetNode) return;
      if (draggedId === targetId || isQaNodeDescendant(draggedNode, targetId)) return;

      if (position === "into") {
        if (draggedNode.parent_ids?.includes(targetId)) return;
        await moveNode(draggedId, [targetId]);
        await fetchQaTree();
        onQaNodeMoved?.(targetId);
        return;
      }

      const targetParentId = getQaNodeParentId(nodesTree, targetId);
      const isSameParent = getQaNodeParentId(nodesTree, draggedId) === targetParentId;
      const siblings = targetParentId === null
        ? nodesTree
        : findQaNode(nodesTree, targetParentId)?.children ?? [];
      const siblingIds = siblings.map((sibling) => sibling.node_id);
      // 跨層時被拖的分類還不在對方的同層清單裡，所以一律先拿掉再插入。
      const ordered = siblingIds.filter((id) => id !== draggedId);
      ordered.splice(
        ordered.indexOf(targetId) + (position === "after" ? 1 : 0),
        0,
        draggedId,
      );
      if (isSameParent && ordered.join("\0") === siblingIds.join("\0")) return;

      if (!isSameParent) {
        await moveNode(draggedId, targetParentId ? [targetParentId] : []);
      }
      await reorderNode(draggedId, ordered);
      await fetchQaTree();
      if (!isSameParent) onQaNodeMoved?.(targetParentId);
    },
    [fetchQaTree, moveNode, nodesTree, onQaNodeMoved, reorderNode],
  );

  const handleTreeDrop = useCallback(
    async (targetDir: string, position: QaDropPosition = "into") => {
      if (!draggingPath) return;
      setDropTarget(targetDir, position);

      const isQaRootDrop = targetDir === QUICK_QA_TREE_PATH;
      const isQaNodeDrop = targetDir.startsWith(`${QUICK_QA_TREE_PATH}/`);
      const draggedQaNodeId = parseQaNodeDragPath(draggingPath);
      const targetQaNodeId = parseQaNodeDragPath(targetDir);
      const draggedQaEntry = parseQaEntryDragPath(draggingPath);
      const targetQaEntry = parseQaEntryDragPath(targetDir);

      const cleanup = () => {
        setDraggingPath(null);
        setDropTarget(null);
      };

      try {
        if (draggedQaEntry && targetQaEntry) {
          if (
            draggedQaEntry.nodeId === targetQaEntry.nodeId &&
            draggedQaEntry.question !== targetQaEntry.question
          ) {
            const mergedRows = await fetchMergedQa(draggedQaEntry.nodeId);
            const dragIdx = mergedRows.findIndex(
              (row) => row.q === draggedQaEntry.question,
            );
            const targetIdx = mergedRows.findIndex(
              (row) => row.q === targetQaEntry.question,
            );

            if (dragIdx !== -1 && targetIdx !== -1) {
              const reorderedRows = [...mergedRows];
              const [draggedRow] = reorderedRows.splice(dragIdx, 1);
              const insertIdx = reorderedRows.findIndex(
                (row) => row.q === targetQaEntry.question,
              );
              reorderedRows.splice(insertIdx, 0, draggedRow);
              // 號碼跟著新順序走：CSV 下次同步時依 index 排序，舊號碼會把順序排回去。
              await saveMergedQa(
                draggedQaEntry.nodeId,
                reorderedRows.map((row, position) => ({ ...row, index: String(position + 1) })),
              );
              if (selectedQaNodeId === draggedQaEntry.nodeId) {
                setMergedRefreshKey((key) => key + 1);
              }
            }
          }
          cleanup();
          return;
        }

        if (draggedQaNodeId && isQaRootDrop) {
          if (getQaNodeParentId(nodesTree, draggedQaNodeId) !== null) {
            await moveNode(draggedQaNodeId, []);
            await fetchQaTree();
            onQaNodeMoved?.(null);
          }
          cleanup();
          return;
        }

        if (draggedQaNodeId && targetQaNodeId) {
          await dropQaNodeOntoNode(draggedQaNodeId, targetQaNodeId, position);
          cleanup();
          return;
        }

        const attachSourceToNode = async (nodeId: string) => {
          const targetNode = findQaNode(nodesTree, nodeId);
          const isDirectoryNode =
            targetNode &&
            (!targetNode.qa_entries || targetNode.qa_entries.length === 0);
          if (isDirectoryNode) {
            await adoptSource(draggingPath, nodeId);
          } else {
            await ingestSource(nodeId, draggingPath);
          }
          loadDocuments();
          if (selectedQaNodeId === nodeId) {
            setMergedRefreshKey((key) => key + 1);
          }
        };

        if (isQaRootDrop) {
          await adoptSource(draggingPath);
          loadDocuments();
        } else if (targetQaNodeId) {
          await attachSourceToNode(targetQaNodeId);
        } else if (isQaNodeDrop) {
          const encodedNodeId = targetDir.substring(
            QUICK_QA_TREE_PATH.length + 1,
          );
          await attachSourceToNode(decodeURIComponent(encodedNodeId));
        } else {
          await handleMove(draggingPath, targetDir);
        }
      } catch (error) {
        // Handled by service notifications/hooks
      } finally {
        cleanup();
      }
    },
    [
      draggingPath,
      dropQaNodeOntoNode,
      handleMove,
      adoptSource,
      ingestSource,
      loadDocuments,
      selectedQaNodeId,
      nodesTree,
      fetchQaTree,
      fetchMergedQa,
      saveMergedQa,
      moveNode,
      onQaNodeMoved,
      setDropTarget,
      setMergedRefreshKey,
    ],
  );

  return {
    draggingPath,
    dropTargetPath,
    dropPosition,
    setDropTarget,
    sourceDragDir,
    canDropQaNode,
    canDropQaEntry,
    handleTreeDragStart,
    handleTreeDragEnd,
    handleTreeDrop,
  };
}
