import { useCallback, useEffect, useMemo, useState } from "react";

import { type QaNode, useQaNodes } from "../../../hooks/useQaNodes";
import AttachSourceModal from "./AttachSourceModal";
import ExplorerSidebar from "./ExplorerSidebar";
import MergedCsvPane from "./MergedCsvPane";

function findNode(nodes: QaNode[], targetId: string): QaNode | undefined {
  for (const node of nodes) {
    if (node.node_id === targetId) {
      return node;
    }
    if (node.children && node.children.length > 0) {
      const found = findNode(node.children, targetId);
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
    attachSource,
    detachSource,
  } = useQaNodes();

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [attachOpen, setAttachOpen] = useState(false);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null;
    return findNode(nodesTree, selectedNodeId) ?? null;
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
          loading={loading}
          error={error}
        />
      </aside>

      <main className="flex-1 min-w-0 p-6 overflow-auto">
        <MergedCsvPane
          nodeId={selectedNodeId}
          nodeLabel={selectedNode?.label}
          onSuccess={handleSuccess}
          onOpenAttachSource={() => setAttachOpen(true)}
        />
      </main>

      <AttachSourceModal
        open={attachOpen}
        node={selectedNode}
        onAttach={attachSource}
        onDetach={detachSource}
        onClose={() => setAttachOpen(false)}
      />
    </div>
  );
}
