import type { KnowledgeDocumentSummary } from "../../api";

/* ── Types ── */

export type SourceMode = "upload" | "web" | "manual";
export type SourceType = SourceMode | "qa";
export type DeleteTarget = { type: "file" | "dir"; value: string } | null;
export type RightPane = "folder" | "file";

export interface TreeNode {
  name: string;
  path: string;
  type: "file" | "folder";
  treeKind?: "qa-root" | "qa-node" | "qa-entry";
  virtual?: boolean;
  qaNodeId?: string;
  qaEntryQuestion?: string;
  qaEntrySourcePath?: string;
  qaHidden?: boolean;
  doc?: KnowledgeDocumentSummary;
  children: TreeNode[];
}

export interface QaEntryInput {
  question: string;
  source_path: string;
  hidden: boolean;
  image_id: string | null;
}

export interface QaTreeNodeInput {
  node_id: string;
  label: string;
  hidden?: boolean;
  qa_entries?: QaEntryInput[];
  children?: QaTreeNodeInput[];
}

/* ── Constants ── */

export const SOURCE_MODES: SourceMode[] = ["upload", "web", "manual"];
export const QUICK_QA_TREE_LABEL = "快速問答";
export const QUICK_QA_TREE_PATH = `knowledge/${QUICK_QA_TREE_LABEL}`;
export const SOURCE_MODE_COPY: Record<SourceMode, string> = {
  upload: "上傳本地文件到目前資料夾。",
  web: "貼網址後擷取頁面內容。",
  manual: "手動建立筆記，支援純文字與 QA 問答格式。",
};

/* ── Formatters ── */

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("zh-TW", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function isUploadDerivedKnowledgeFile(doc: { source_type: string; path: string }): boolean {
  return doc.source_type === "upload" && doc.path.startsWith("knowledge/");
}

export function getSourceMeta(sourceType: SourceType) {
  switch (sourceType) {
    case "web":
      return { icon: "language", label: "網頁", chipClass: "border-sky-500/30 bg-sky-500/10 text-sky-300" };
    case "manual":
      return { icon: "edit_note", label: "手動", chipClass: "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300" };
    case "qa":
      return { icon: "quiz", label: "QA", chipClass: "border-amber-500/30 bg-amber-500/10 text-amber-300" };
    default:
      return { icon: "upload_file", label: "上傳", chipClass: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
  }
}

export function normalizeSearchTerm(search: string): string {
  return search.trim().toLowerCase();
}

export function matchesKnowledgeDocumentSearch(document: KnowledgeDocumentSummary, search: string): boolean {
  const normalizedSearch = normalizeSearchTerm(search);
  if (!normalizedSearch) {
    return true;
  }

  return document.path.toLowerCase().includes(normalizedSearch) ||
    document.title.toLowerCase().includes(normalizedSearch) ||
    document.preview.toLowerCase().includes(normalizedSearch) ||
    (document.source_url ?? "").toLowerCase().includes(normalizedSearch);
}

/* ── Tree Builder ── */

export function buildTree(documents: KnowledgeDocumentSummary[], serverDirs: string[]): TreeNode {
  const root: TreeNode = { name: "knowledge", path: "knowledge", type: "folder", children: [] };

  function ensureFolder(path: string): TreeNode {
    const parts = path.split("/");
    let current = root;
    for (let i = 1; i < parts.length; i++) {
      const segment = parts[i];
      const childPath = parts.slice(0, i + 1).join("/");
      let child = current.children.find((c) => c.path === childPath && c.type === "folder");
      if (!child) {
        child = { name: segment, path: childPath, type: "folder", children: [] };
        current.children.push(child);
      }
      current = child;
    }
    return current;
  }

  for (const dir of serverDirs) {
    if (dir.startsWith("knowledge")) ensureFolder(dir);
  }

  for (const doc of documents) {
    const parts = doc.path.split("/");
    const parentPath = parts.slice(0, -1).join("/");
    const parent = parentPath ? ensureFolder(parentPath) : root;
    parent.children.push({
      name: parts[parts.length - 1],
      path: doc.path,
      type: "file",
      doc,
      children: [],
    });
  }

  function sortChildren(node: TreeNode): void {
    node.children.sort((a, b) => {
      if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    node.children.forEach(sortChildren);
  }
  sortChildren(root);

  return root;
}

export function filterTree(node: TreeNode, normalizedSearch: string): TreeNode | null {
  if (!normalizedSearch) {
    return node;
  }

  const matchesSelf = node.doc
    ? matchesKnowledgeDocumentSearch(node.doc, normalizedSearch)
    : node.name.toLowerCase().includes(normalizedSearch) ||
      node.path.toLowerCase().includes(normalizedSearch);

  if (node.type === "file") {
    return matchesSelf ? node : null;
  }

  const children = node.children
    .map((child) => filterTree(child, normalizedSearch))
    .filter((child): child is TreeNode => child !== null);

  if (!matchesSelf && children.length === 0) {
    return null;
  }

  return {
    ...node,
    children,
  };
}

export function countFiles(node: TreeNode): number {
  if (node.type === "file") return 1;
  return node.children.reduce((sum, child) => sum + countFiles(child), 0);
}

export function collectFolderPaths(node: TreeNode): string[] {
  if (node.type === "file") {
    return [];
  }

  return [node.path, ...node.children.flatMap(collectFolderPaths)];
}

export function qaTreeNodePath(nodeId: string): string {
  return `${QUICK_QA_TREE_PATH}/${encodeURIComponent(nodeId)}`;
}

export function qaTreeEntryPath(nodeId: string, question: string): string {
  return `${qaTreeNodePath(nodeId)}/entry/${encodeURIComponent(question)}`;
}

export function qaNodeDragPath(nodeId: string): string {
  return `qa_node:${encodeURIComponent(nodeId)}`;
}

export function qaEntryDragPath(nodeId: string, question: string): string {
  return `qa_entry:${encodeURIComponent(nodeId)}:${encodeURIComponent(question)}`;
}

export function parseQaNodeDragPath(path: string): string | null {
  if (!path.startsWith("qa_node:")) return null;
  try {
    return decodeURIComponent(path.slice("qa_node:".length));
  } catch {
    return null;
  }
}

export function parseQaEntryDragPath(path: string): { nodeId: string; question: string } | null {
  if (!path.startsWith("qa_entry:")) return null;
  const value = path.slice("qa_entry:".length);
  const separatorIndex = value.indexOf(":");
  if (separatorIndex === -1) return null;

  try {
    return {
      nodeId: decodeURIComponent(value.slice(0, separatorIndex)),
      question: decodeURIComponent(value.slice(separatorIndex + 1)),
    };
  } catch {
    return null;
  }
}

function qaNodeMatchesSearch(node: QaTreeNodeInput, normalizedSearch: string): boolean {
  return node.label.toLowerCase().includes(normalizedSearch) ||
    node.node_id.toLowerCase().includes(normalizedSearch);
}

function qaNodeToTreeNode(
  node: QaTreeNodeInput,
  normalizedSearch: string,
): TreeNode | null {
  const childNodes = (node.children ?? [])
    .map((child) => qaNodeToTreeNode(child, normalizedSearch))
    .filter((child): child is TreeNode => child !== null);

  const entries: TreeNode[] = (node.qa_entries ?? [])
    .filter((entry) => !normalizedSearch || entry.question.toLowerCase().includes(normalizedSearch))
    .map((entry) => ({
      name: entry.question,
      path: qaTreeEntryPath(node.node_id, entry.question),
      type: "file" as const,
      treeKind: "qa-entry" as const,
      virtual: true,
      qaNodeId: node.node_id,
      qaEntryQuestion: entry.question,
      qaEntrySourcePath: entry.source_path,
      qaHidden: Boolean(entry.hidden),
      children: [],
    }));

  const allChildren = [...childNodes, ...entries];
  const matchesSelf = !normalizedSearch || qaNodeMatchesSearch(node, normalizedSearch);

  if (!matchesSelf && allChildren.length === 0) {
    return null;
  }

  return {
    name: node.label || node.node_id,
    path: qaTreeNodePath(node.node_id),
    type: "folder",
    treeKind: "qa-node",
    virtual: true,
    qaNodeId: node.node_id,
    qaHidden: Boolean(node.hidden),
    children: allChildren,
  };
}

export function mergeQaNodesIntoTree(
  documentTree: TreeNode,
  qaNodes: QaTreeNodeInput[],
  search = "",
): TreeNode {
  const normalizedSearch = normalizeSearchTerm(search);
  const qaChildren = qaNodes
    .map((node) => qaNodeToTreeNode(node, normalizedSearch))
    .filter((node): node is TreeNode => node !== null);
  const rootMatches = QUICK_QA_TREE_LABEL.toLowerCase().includes(normalizedSearch) ||
    QUICK_QA_TREE_PATH.toLowerCase().includes(normalizedSearch);
  const shouldShowQaRoot = !normalizedSearch || rootMatches || qaChildren.length > 0;
  const children = [...documentTree.children];

  if (shouldShowQaRoot) {
    children.push({
      name: QUICK_QA_TREE_LABEL,
      path: QUICK_QA_TREE_PATH,
      type: "folder",
      treeKind: "qa-root",
      virtual: true,
      children: qaChildren,
    });
  }

  return {
    ...documentTree,
    children,
  };
}
