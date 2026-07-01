import { useCallback, useEffect, useMemo, useState } from "react";

import { type QaNode, useQaNodes } from "../../../hooks/useQaNodes";
import ExplorerSidebar from "./ExplorerSidebar";
import MergedCsvPane from "./MergedCsvPane";
import UploadDialog from "./UploadDialog";

function findNodeLabel(nodes: QaNode[], targetId: string): string | undefined {
  for (const node of nodes) {
    if (node.node_id === targetId) {
      return node.label;
    }
    if (node.children && node.children.length > 0) {
      const found = findNodeLabel(node.children, targetId);
      if (found) return found;
    }
  }
  return undefined;
}

export default function QaNodeWorkspace() {
  const {
    nodesTree,
    loading,
    error,
    fetchTree,
    createNode,
    updateNode,
    deleteNode,
    reorderNode,
  } = useQaNodes();

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  const selectedNodeLabel = useMemo(() => {
    if (!selectedNodeId) return undefined;
    return findNodeLabel(nodesTree, selectedNodeId);
  }, [nodesTree, selectedNodeId]);

  const handleDeleteNode = useCallback(async (id: string) => {
    const res = await deleteNode(id);
    if (selectedNodeId === id) {
      setSelectedNodeId(null);
    }
    return res;
  }, [deleteNode, selectedNodeId]);

  const handleSuccess = useCallback(() => {
    fetchTree();
  }, [fetchTree]);

  return (
    <div className="flex-1 flex min-h-0 overflow-hidden bg-slate-50 dark:bg-background-dark">
      <aside className="w-64 xl:w-72 shrink-0 border-r border-slate-200 dark:border-slate-800/60 flex flex-col bg-white dark:bg-slate-950/30 overflow-hidden">
        <ExplorerSidebar
          nodesTree={nodesTree}
          selectedNodeId={selectedNodeId}
          onSelectNode={setSelectedNodeId}
          onCreateNode={createNode}
          onUpdateNode={updateNode}
          onDeleteNode={handleDeleteNode}
          onReorderNode={reorderNode}
          onUploadClick={() => setUploadOpen(true)}
          loading={loading}
          error={error}
        />
      </aside>

      <main className="flex-1 min-w-0 p-6 overflow-auto">
        <MergedCsvPane
          nodeId={selectedNodeId}
          nodeLabel={selectedNodeLabel}
          onSuccess={handleSuccess}
        />
      </main>

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        nodesTree={nodesTree}
        defaultNodeId={selectedNodeId || undefined}
        onSuccess={handleSuccess}
      />
    </div>
  );
}
