import type { KnowledgeDocumentSummary } from "../../api";

/* ── Types ── */

export type SourceMode = "upload" | "web" | "manual";
export type DeleteTarget = { type: "file" | "dir"; value: string } | null;
export type RightPane = "folder" | "file";

export interface TreeNode {
  name: string;
  path: string;
  type: "file" | "folder";
  doc?: KnowledgeDocumentSummary;
  children: TreeNode[];
}

/* ── Constants ── */

export const SOURCE_MODES: SourceMode[] = ["upload", "web", "manual"];
export const SOURCE_MODE_COPY: Record<SourceMode, string> = {
  upload: "上傳本地檔案到目前資料夾。",
  web: "貼網址後擷取頁面內容。",
  manual: "直接貼上筆記或整理好的內容，存成可索引來源。",
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

export function getSourceMeta(sourceType: SourceMode) {
  switch (sourceType) {
    case "web":
      return { icon: "language", label: "網頁", chipClass: "border-sky-500/30 bg-sky-500/10 text-sky-300" };
    case "manual":
      return { icon: "edit_note", label: "手動", chipClass: "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300" };
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

  const ensureFolder = (path: string): TreeNode => {
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
  };

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

  const sortChildren = (node: TreeNode) => {
    node.children.sort((a, b) => {
      if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    node.children.forEach(sortChildren);
  };
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
