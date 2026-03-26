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

/* ── Directory Queries ── */

export function getFilesInDir(documents: KnowledgeDocumentSummary[], dir: string): KnowledgeDocumentSummary[] {
  const prefix = dir ? `${dir}/` : "";
  return documents.filter((doc) => {
    if (!doc.path.startsWith(prefix)) return false;
    const rest = doc.path.slice(prefix.length);
    return !rest.includes("/");
  });
}

export function getSubdirs(documents: KnowledgeDocumentSummary[], serverDirs: string[], dir: string): string[] {
  const prefix = dir ? `${dir}/` : "";
  const subdirs = new Set<string>();
  for (const doc of documents) {
    if (!doc.path.startsWith(prefix)) continue;
    const rest = doc.path.slice(prefix.length);
    const slashIdx = rest.indexOf("/");
    if (slashIdx !== -1) subdirs.add(rest.slice(0, slashIdx));
  }
  for (const d of serverDirs) {
    if (!d.startsWith(prefix)) continue;
    const rest = d.slice(prefix.length);
    const slashIdx = rest.indexOf("/");
    const sub = slashIdx === -1 ? rest : rest.slice(0, slashIdx);
    if (sub) subdirs.add(sub);
  }
  return [...subdirs].sort();
}
