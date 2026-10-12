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
        const pathsToExpand = ["quick_qa_tree_root"];
        let currentPath = "quick_qa_tree_root";
        for (const id of ancestors) {
          currentPath = `${currentPath}/${encodeURIComponent(id)}`;
          pathsToExpand.push(currentPath);
        }
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
