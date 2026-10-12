import {
  useCallback,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { TreeNode } from "../components/kb/helpers";
import {
  findQaNode,
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
}: UseKnowledgeTreeDragDropOptions) {
  const [draggingPath, setDraggingPath] = useState<string | null>(null);
  const [dropTargetPath, setDropTargetPath] = useState<string | null>(null);

  const canDropQaNode = useCallback(
    (draggedPath: string, targetPath: string) => {
      const draggedNodeId = parseQaNodeDragPath(draggedPath);
      const targetNodeId = parseQaNodeDragPath(targetPath);
      if (!draggedNodeId || !targetNodeId) return false;
      if (draggedNodeId === targetNodeId) return false;

      const draggedNode = findQaNode(nodesTree, draggedNodeId);
      const targetNode = findQaNode(nodesTree, targetNodeId);
      if (!draggedNode || !targetNode) return false;

      // 同父層 = 排序; 跨父層 = 換父層(re-parent), 但不能移進自己的子孫
      return !isQaNodeDescendant(draggedNode, targetNodeId);
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
    setDropTargetPath(null);
  }, []);

  const handleTreeDrop = useCallback(
    async (targetDir: string) => {
      if (!draggingPath) return;
      setDropTargetPath(targetDir);

      const isQaRootDrop = targetDir === QUICK_QA_TREE_PATH;
      const isQaNodeDrop = targetDir.startsWith(`${QUICK_QA_TREE_PATH}/`);
      const draggedQaNodeId = parseQaNodeDragPath(draggingPath);
      const targetQaNodeId = parseQaNodeDragPath(targetDir);
      const draggedQaEntry = parseQaEntryDragPath(draggingPath);
      const targetQaEntry = parseQaEntryDragPath(targetDir);

      const cleanup = () => {
        setDraggingPath(null);
        setDropTargetPath(null);
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
              await saveMergedQa(draggedQaEntry.nodeId, reorderedRows);
              if (selectedQaNodeId === draggedQaEntry.nodeId) {
                setMergedRefreshKey((key) => key + 1);
              }
            }
          }
          cleanup();
          return;
        }

        if (draggedQaNodeId && isQaRootDrop) {
          const draggedNode = findQaNode(nodesTree, draggedQaNodeId);
          if (draggedNode && (draggedNode.parent_ids?.length ?? 0) > 0) {
            await moveNode(draggedQaNodeId, []);
            await fetchQaTree();
          }
          cleanup();
          return;
        }

        if (draggedQaNodeId && targetQaNodeId) {
          const draggedNodeId = draggedQaNodeId;
          const targetNodeId = targetQaNodeId;
          if (draggedNodeId !== targetNodeId) {
            const draggedNode = findQaNode(nodesTree, draggedNodeId);
            const targetNode = findQaNode(nodesTree, targetNodeId);
            const draggingParentId = draggedNode?.parent_ids?.[0] || null;
            const targetParentId = targetNode?.parent_ids?.[0] || null;

            if (draggingParentId === targetParentId) {
              const siblings =
                draggingParentId === null
                  ? nodesTree
                  : findQaNode(nodesTree, draggingParentId)?.children || [];

              const siblingIds = siblings.map((s) => s.node_id);
              const dragIdx = siblingIds.indexOf(draggedNodeId);
              const targetIdx = siblingIds.indexOf(targetNodeId);

              if (dragIdx !== -1 && targetIdx !== -1) {
                const newOrdered = [...siblingIds];
                newOrdered.splice(dragIdx, 1);
                const insertIdx = newOrdered.indexOf(targetNodeId);
                newOrdered.splice(insertIdx, 0, draggedNodeId);
                await reorderNode(draggedNodeId, newOrdered);
                await fetchQaTree();
              }
            } else {
              await moveNode(draggedNodeId, [targetNodeId]);
              await fetchQaTree();
            }
          }
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
        } else if (targetDir === "" && selectedQaNodeId) {
          await attachSourceToNode(selectedQaNodeId);
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
      handleMove,
      adoptSource,
      ingestSource,
      loadDocuments,
      selectedQaNodeId,
      nodesTree,
      reorderNode,
      fetchQaTree,
      fetchMergedQa,
      saveMergedQa,
      moveNode,
      setMergedRefreshKey,
    ],
  );

  return {
    draggingPath,
    dropTargetPath,
    setDropTargetPath,
    sourceDragDir,
    canDropQaNode,
    canDropQaEntry,
    handleTreeDragStart,
    handleTreeDragEnd,
    handleTreeDrop,
  };
}
