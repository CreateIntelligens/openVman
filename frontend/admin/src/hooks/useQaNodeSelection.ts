import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  findQaNode,
  getFileParentPaths,
  getQaNodeAncestors,
  QUICK_QA_TREE_PATH,
  qaTreeNodePath,
} from "../components/kb/helpers";
import type { QaNode } from "./useQaNodes";
import { readScoped, removeScoped } from "../utils/scopedStorage";

interface UseQaNodeSelectionOptions {
  projectId: string;
  nodesTree: QaNode[];
  qaTreeLoading: boolean;
  selectedPath: string;
  setExpandedDirs: Dispatch<SetStateAction<Set<string>>>;
}

export function useQaNodeSelection({
  projectId,
  nodesTree,
  qaTreeLoading,
  selectedPath,
  setExpandedDirs,
}: UseQaNodeSelectionOptions) {
  const [qaSelection, setQaSelection] = useState(() => ({
    projectId,
    nodeId: readScoped(`kb-selected-qa-node-id:${projectId}`),
  }));

  const selectedQaNodeId =
    qaSelection.projectId === projectId ? qaSelection.nodeId : null;

  const setSelectedQaNodeId = useCallback(
    (next: SetStateAction<string | null>) => {
      setQaSelection((current) => {
        const currentNodeId =
          current.projectId === projectId ? current.nodeId : null;
        return {
          projectId,
          nodeId: typeof next === "function" ? next(currentNodeId) : next,
        };
      });
    },
    [projectId],
  );

  useEffect(() => {
    setSelectedQaNodeId(readScoped(`kb-selected-qa-node-id:${projectId}`));
  }, [projectId]);

  useEffect(() => {
    if (
      qaTreeLoading ||
      !selectedQaNodeId ||
      findQaNode(nodesTree, selectedQaNodeId)
    )
      return;
    removeScoped(`kb-selected-qa-node-id:${projectId}`);
    setSelectedQaNodeId(null);
  }, [nodesTree, projectId, qaTreeLoading, selectedQaNodeId]);

  useEffect(() => {
    if (selectedQaNodeId && nodesTree.length > 0) {
      const ancestors = getQaNodeAncestors(nodesTree, selectedQaNodeId);
      if (ancestors) {
        // 只展開上層讓它看得到；它自己要不要展開由使用者決定，樹一更新就會再跑一次這裡。
        const pathsToExpand = [QUICK_QA_TREE_PATH, ...ancestors.map(qaTreeNodePath)];
        setExpandedDirs((prev) => {
          const next = new Set(prev);
          let changed = false;
          for (const path of pathsToExpand) {
            if (!next.has(path)) {
              next.add(path);
              changed = true;
            }
          }
          return changed ? next : prev;
        });
      }
    } else if (selectedPath && selectedPath !== "knowledge") {
      const pathsToExpand = getFileParentPaths(selectedPath);
      setExpandedDirs((prev) => {
        const next = new Set(prev);
        let changed = false;
        for (const path of pathsToExpand) {
          if (!next.has(path)) {
            next.add(path);
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }
  }, [selectedQaNodeId, selectedPath, nodesTree, setExpandedDirs]);

  const selectedQaNode = useMemo(() => {
    if (!selectedQaNodeId) return null;
    return findQaNode(nodesTree, selectedQaNodeId) ?? null;
  }, [nodesTree, selectedQaNodeId]);

  return { selectedQaNodeId, setSelectedQaNodeId, selectedQaNode };
}
