import React, { useState, useEffect, useMemo } from "react";
import { 
  fetchKnowledgeBaseDocuments, 
  fetchKnowledgeDocument, 
  saveKnowledgeDocument,
  KnowledgeDocumentSummary 
} from "../../api";
import FilesTree from "./FilesTree";
import FileEditor from "./FileEditor";
import { KBNode, KBNodeStatus } from "./types";
import StatusAlert from "../StatusAlert";

const KnowledgeBaseAdmin: React.FC = () => {
  const [nodes, setNodes] = useState<KBNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<KBNode | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTree = async () => {
    setLoading(true);
    try {
      const resp = await fetchKnowledgeBaseDocuments();
      const tree = buildTree(resp.documents);
      setNodes(tree);
    } catch (err: any) {
      setError(err.message || "Failed to load knowledge base");
    } finally {
      setLoading(false);
    }
  };

  const buildTree = (docs: KnowledgeDocumentSummary[]): KBNode[] => {
    const treeRoot: KBNode[] = [];
    const map: { [key: string]: KBNode } = {};

    docs.forEach(doc => {
      const parts = doc.path.split("/");
      let parentPath = "";
      
      parts.forEach((part, i) => {
        const fullPath = parentPath ? `${parentPath}/${part}` : part;
        const isFile = i === parts.length - 1;

        if (!map[fullPath]) {
          const newNode: KBNode = {
            id: fullPath,
            name: isFile ? doc.title || part : part,
            type: isFile ? "file" : "folder",
            status: isFile ? (doc.is_indexed ? "indexed" : "syncing") : "indexed",
          };
          if (!isFile) newNode.children = [];
          map[fullPath] = newNode;

          if (parentPath === "") {
            treeRoot.push(newNode);
          } else {
            map[parentPath].children?.push(newNode);
          }
        }
        parentPath = fullPath;
      });
    });

    return treeRoot;
  };

  useEffect(() => {
    loadTree();
  }, []);

  const handleSelect = async (node: KBNode) => {
    if (node.type === "file") {
      setLoading(true);
      setSelectedNode(node);
      try {
        const doc = await fetchKnowledgeDocument(node.id);
        setFileContent(doc.content);
      } catch (err: any) {
        setError(err.message || "Failed to load document content");
      } finally {
        setLoading(false);
      }
    } else {
      setSelectedNode(node);
      setFileContent("");
    }
  };

  const handleSave = async (path: string, content: string) => {
    setSaving(true);
    try {
      await saveKnowledgeDocument(path, content);
      // Optimistic update of content
      setFileContent(content);
      // Refresh tree to get updated status
      await loadTree();
    } catch (err: any) {
      setError(err.message || "Failed to save document");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex h-full w-full overflow-hidden bg-slate-50 dark:bg-background p-4 lg:p-6 gap-6 transition-colors">
      {/* Sidebar Tree */}
      <aside className="w-[300px] flex-shrink-0 flex flex-col bg-white dark:bg-slate-900/30 rounded-2xl border border-slate-200 dark:border-slate-800/60 overflow-hidden shadow-sm dark:shadow-none transition-all">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800/60 flex items-center justify-between bg-slate-50 dark:bg-slate-900/10">
          <h2 className="text-xs font-bold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400 transition-colors">Library</h2>
          <button 
            onClick={loadTree}
            className="p-1.5 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-800/60 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-all"
            disabled={loading}
          >
            <span className={`material-symbols-outlined text-[18px] ${loading ? 'animate-spin' : ''}`}>sync</span>
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-3 scrollbar-none hover:scrollbar-thin">
          <FilesTree 
            nodes={nodes} 
            selectedId={selectedNode?.id || null} 
            onSelect={handleSelect} 
          />
        </div>
      </aside>

      {/* Main Content / Editor */}
      <main className="flex-1 min-w-0 flex flex-col">
        {error && (
          <div className="mb-4">
            <StatusAlert type="error" message={error} onDismiss={() => setError(null)} />
          </div>
        )}

        {selectedNode && selectedNode.type === "file" ? (
          <FileEditor 
            path={selectedNode.id} 
            content={fileContent} 
            onSave={handleSave}
            saving={saving}
          />
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center bg-white dark:bg-slate-950/20 rounded-2xl border border-slate-200 dark:border-slate-800/60 border-dashed shadow-sm dark:shadow-none transition-all">
            <div className="w-20 h-20 rounded-full bg-slate-50 dark:bg-slate-900/50 flex items-center justify-center mb-4 border border-slate-200 dark:border-slate-800/60 shadow-xl dark:shadow-2xl transition-all">
              <span className="material-symbols-outlined text-4xl text-slate-400 dark:text-slate-600">edit_note</span>
            </div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-white mb-2">Knowledge Base Admin</h3>
            <p className="text-sm text-slate-500 dark:text-slate-500 max-w-xs text-center leading-relaxed">
              Select a file from the library to start editing, or create a new document in the workspace.
            </p>
          </div>
        )}
      </main>
    </div>
  );
};

export default KnowledgeBaseAdmin;
