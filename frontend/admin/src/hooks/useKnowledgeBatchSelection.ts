import { useCallback, useEffect, useMemo, useState } from "react";
import type { KnowledgeDocument, KnowledgeDocumentSummary } from "../api";
import type { BatchActionKind } from "../components/kb/BatchActionBar";

interface UseKnowledgeBatchSelectionOptions {
  projectId: string;
  documents: KnowledgeDocumentSummary[];
  openDocument: KnowledgeDocument | null;
  loadDocuments: () => Promise<void>;
  closeFileView: () => void;
  handleTreeSelect: (node: { type: string; path: string }) => void;
  fetchQaTree: () => Promise<unknown>;
}

export function useKnowledgeBatchSelection({
  projectId,
  documents,
  openDocument,
  loadDocuments,
  closeFileView,
  handleTreeSelect,
  fetchQaTree,
}: UseKnowledgeBatchSelectionOptions) {
  const [multiSelect, setMultiSelect] = useState(false);
  const [checkedFilePaths, setCheckedFilePaths] = useState<string[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);

  useEffect(() => {
    setMultiSelect(false);
    setCheckedFilePaths([]);
  }, [projectId]);

  // 已被移走或刪掉的路徑不再算選取，避免「已選 N 個」數字與樹上勾選不一致。
  const batchSelectedPaths = useMemo(() => {
    const existing = new Set(documents.map((document) => document.path));
    return checkedFilePaths.filter((path) => existing.has(path));
  }, [checkedFilePaths, documents]);

  const checkedPathSet = useMemo(
    () => new Set(batchSelectedPaths),
    [batchSelectedPaths],
  );

  const handleToggleMultiSelect = useCallback(() => {
    if (batchRunning) return;
    setMultiSelect((current) => !current);
    setCheckedFilePaths([]);
  }, [batchRunning]);

  const handleToggleChecked = useCallback(
    (paths: string[], checked: boolean) => {
      if (batchRunning) return;
      setCheckedFilePaths((current) => {
        if (checked) return [...new Set([...current, ...paths])];
        const removed = new Set(paths);
        return current.filter((path) => !removed.has(path));
      });
    },
    [batchRunning],
  );

  const handleBatchFinished = useCallback(
    async (
      action: BatchActionKind,
      succeeded: string[],
      targetPathOf: (path: string) => string,
    ) => {
      await loadDocuments();
      const openPath = openDocument?.path;
      if (openPath && succeeded.includes(openPath)) {
        if (action === "delete") {
          closeFileView();
        } else {
          handleTreeSelect({ type: "file", path: targetPathOf(openPath) });
        }
      }
      // 搬移與刪除都可能改到 QA 文件，後端會同步改問答樹的來源。
      if (action !== "language") {
        await fetchQaTree().catch(() => undefined);
      }
    },
    [closeFileView, fetchQaTree, handleTreeSelect, loadDocuments, openDocument],
  );

  return {
    multiSelect,
    batchRunning,
    setBatchRunning,
    setCheckedFilePaths,
    batchSelectedPaths,
    checkedPathSet,
    handleToggleMultiSelect,
    handleToggleChecked,
    handleBatchFinished,
  };
}
