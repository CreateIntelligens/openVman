import type { KnowledgeDocumentSummary, KnowledgeLanguage } from "../../api";
import type { QaNode } from "../../hooks/useQaNodes";
import { isLanguageCategoryLabel } from "./qa/languageCategories";

/* ── Types ── */

export type SourceType = "upload" | "web" | "manual" | "qa";
export type DeleteTarget = { type: "file" | "dir"; value: string } | null;
export type RightPane = "folder" | "file";

export interface TreeNode {
  name: string;
  path: string;
  type: "file" | "folder";
  /**
   * sections：不顯示的外層，子項就是兩個段落。
   * qa-root、documents-root：段落列「快速問答」與「文件」。
   */
  treeKind?: "sections" | "qa-root" | "documents-root" | "qa-node" | "qa-entry";
  virtual?: boolean;
  qaNodeId?: string;
  qaEntryQuestion?: string;
  qaEntrySourcePath?: string;
  qaHidden?: boolean;
  /** 第一層、名字是「中文」「English」這類的分類，改名會影響匯入與訪客選單。 */
  qaLanguageCategory?: boolean;
  /** 這個分類自己的題數，不含子分類。 */
  qaQuestionCount?: number;
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

export const QUICK_QA_TREE_LABEL = "快速問答";
export const QUICK_QA_TREE_PATH = `knowledge/${QUICK_QA_TREE_LABEL}`;
export const DOCUMENTS_SECTION_LABEL = "文件";
export const DOCUMENTS_ROOT_PATH = "knowledge";
const TREE_SECTIONS_PATH = "__tree_sections__";
export const KNOWLEDGE_LANGUAGE_LABELS: Record<KnowledgeLanguage, string> = {
  zh: "中文",
  en: "English",
  es: "Español",
  nan: "台語",
  ja: "日本語",
  ko: "한국어",
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

export function hasOriginalBackup(doc: { has_original_backup?: boolean }): boolean {
  return doc.has_original_backup === true;
}

/** 畫面上顯示的文件路徑：knowledge/ 是內部前綴，樹上也看不到這一層。 */
export function displayDocumentPath(path: string): string {
  return path.replace(/^knowledge(\/|$)/, "");
}

// 色相只放在底色與框線：淺色模式下 success、primary 當小字的對比不到 4.5:1，字一律用 content。
export function getSourceMeta(sourceType: SourceType) {
  switch (sourceType) {
    case "web":
      return { icon: "language", label: "貼網址", chipClass: "border-info/30 bg-info/10 text-content" };
    case "manual":
      return { icon: "edit_note", label: "自己輸入", chipClass: "border-primary/30 bg-primary/10 text-content" };
    case "qa":
      return { icon: "quiz", label: "問答", chipClass: "border-warn/30 bg-warn/10 text-content" };
    default:
      return { icon: "upload_file", label: "上傳", chipClass: "border-success/30 bg-success/10 text-content" };
  }
}

export function normalizeSearchTerm(search: string): string {
  return search.trim().toLowerCase();
}

// knowledge/ 是內部前綴，畫面上看不到；留著的話搜「know」會把全部文件都搜出來。
function searchablePath(path: string): string {
  return displayDocumentPath(path).toLowerCase();
}

export function matchesKnowledgeDocumentSearch(document: KnowledgeDocumentSummary, search: string): boolean {
  const normalizedSearch = normalizeSearchTerm(search);
  if (!normalizedSearch) {
    return true;
  }

  return searchablePath(document.path).includes(normalizedSearch) ||
    document.title.toLowerCase().includes(normalizedSearch) ||
    document.preview.toLowerCase().includes(normalizedSearch) ||
    (document.source_url ?? "").toLowerCase().includes(normalizedSearch);
}

/* ── Tree Builder ── */

const QA_STORAGE_DIR = "knowledge/qa";

function isInQaStorage(path: string): boolean {
  return path === QA_STORAGE_DIR || path.startsWith(`${QA_STORAGE_DIR}/`);
}

/** 掛在快速問答的問答文件，由上面的「快速問答」段落管理，文件段落不再列出。 */
export function isManagedQaDocument(document: KnowledgeDocumentSummary): boolean {
  return document.source_type === "qa" && document.qa_attached === true && isInQaStorage(document.path);
}

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
    // 資料夾跟著裡面看得到的文件才出現：沒掛上快速問答的問答文件要留著，否則找不到也刪不掉。
    if (dir.startsWith("knowledge") && !isInQaStorage(dir)) ensureFolder(dir);
  }

  for (const doc of documents) {
    if (isManagedQaDocument(doc)) continue;
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
      searchablePath(node.path).includes(normalizedSearch);

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

// 內部編號畫面上看不到，不拿來比對：搜「qa」不該跑出每個 qa_node_* 分類。
function qaNodeMatchesSearch(node: QaTreeNodeInput, normalizedSearch: string): boolean {
  return node.label.toLowerCase().includes(normalizedSearch);
}

function qaNodeToTreeNode(
  node: QaTreeNodeInput,
  normalizedSearch: string,
  topLevel = false,
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
    qaLanguageCategory: topLevel && isLanguageCategoryLabel(node.label),
    // 用未過濾的題數：搜尋時數字不跟著跳，看到的永遠是這個分類真正有幾題。
    qaQuestionCount: node.qa_entries?.length ?? 0,
    children: allChildren,
  };
}

/** 樹的兩段：快速問答在前、文件在後，由不顯示的外層包住。 */
export function mergeQaNodesIntoTree(
  documentTree: TreeNode,
  qaNodes: QaTreeNodeInput[],
  search = "",
): TreeNode {
  const normalizedSearch = normalizeSearchTerm(search);
  const qaSection: TreeNode = {
    name: QUICK_QA_TREE_LABEL,
    path: QUICK_QA_TREE_PATH,
    type: "folder",
    treeKind: "qa-root",
    virtual: true,
    children: qaNodes
      .map((node) => qaNodeToTreeNode(node, normalizedSearch, true))
      .filter((node): node is TreeNode => node !== null),
  };
  const documentsSection: TreeNode = {
    ...documentTree,
    name: DOCUMENTS_SECTION_LABEL,
    treeKind: "documents-root",
  };
  const sections = [qaSection, documentsSection];

  return {
    name: "",
    path: TREE_SECTIONS_PATH,
    type: "folder",
    treeKind: "sections",
    virtual: true,
    // 搜尋時只留有結果的段落，外層 children 是空的就代表沒有東西可顯示。
    children: normalizedSearch
      ? sections.filter((section) => section.children.length > 0)
      : sections,
  };
}

/** 搜尋結果的筆數：沒有下一層的列才算一筆，中間層只是帶路。 */
export function countSearchResults(tree: TreeNode): number {
  return tree.children.reduce(
    (sum, child) => sum + (child.children.length > 0 ? countSearchResults(child) : 1),
    0,
  );
}

const FILE_NAME_TAIL_COLUMNS = 12;
const FILE_NAME_MIN_HEAD_COLUMNS = 4;
const WIDE_CHARACTER_START = 0x2e80;

// 中日韓文字和 emoji 大約佔兩個英數字寬。照字數算的話，十幾個中文字的檔名明明放不下
// 卻不會被切開，只差尾巴的兩份文件在樹上看起來一模一樣。
function displayColumns(character: string): number {
  return (character.codePointAt(0) ?? 0) >= WIDE_CHARACTER_START ? 2 : 1;
}

/**
 * 把檔名切成會被省略的 head 與永遠顯示的 tail，CSS 就能省略中間、留住結尾，
 * 長檔名才分得出「_IMG_PRP_1.csv」和「_IMG_PRP_2.csv」。短檔名不切。
 */
export function splitFileNameForDisplay(name: string): { head: string; tail: string } {
  // 依碼位切，emoji 這類字元才不會被切成兩半。
  const characters = Array.from(name);
  const columns = characters.map(displayColumns);
  const totalColumns = columns.reduce((sum, width) => sum + width, 0);
  if (totalColumns <= FILE_NAME_TAIL_COLUMNS + FILE_NAME_MIN_HEAD_COLUMNS) {
    return { head: name, tail: "" };
  }
  let tailStart = characters.length;
  let tailColumns = 0;
  while (tailColumns + columns[tailStart - 1] <= FILE_NAME_TAIL_COLUMNS) {
    tailStart -= 1;
    tailColumns += columns[tailStart];
  }
  return {
    head: characters.slice(0, tailStart).join(""),
    tail: characters.slice(tailStart).join(""),
  };
}

export type QaDropPosition = "before" | "into" | "after";

/** 拖曳分類時，游標在目標列的上下 25% 是排序，中間是放進去。 */
export function qaDropPositionAt(
  clientY: number,
  rect: { top: number; height: number },
): QaDropPosition {
  // 量不到列高時當作放進去，寧可多一步也不要默默改順序。
  if (rect.height <= 0) return "into";
  const ratio = (clientY - rect.top) / rect.height;
  if (ratio < 0.25) return "before";
  if (ratio > 0.75) return "after";
  return "into";
}


/* ── QA 節點樹的走訪 ──
 * 從 KnowledgeBase.tsx 搬出來的，行為未改。純函式，不依賴 React。
 */

export function findQaNodeMatching(nodes: QaNode[], predicate: (node: QaNode) => boolean): QaNode | undefined {
  for (const node of nodes) {
    if (predicate(node)) {
      return node;
    }
    if (node.children && node.children.length > 0) {
      const found = findQaNodeMatching(node.children, predicate);
      if (found) return found;
    }
  }
  return undefined;
}

export function findQaNode(nodes: QaNode[], targetId: string): QaNode | undefined {
  return findQaNodeMatching(nodes, (node) => node.node_id === targetId);
}

export function findNodeReferencingSource(nodes: QaNode[], sourcePath: string): QaNode | undefined {
  return findQaNodeMatching(nodes, (node) =>
    (node.qa_entries ?? []).some((entry) => entry.source_path === sourcePath));
}

export function getFileParentPaths(path: string): string[] {
  const parts = path.split("/");
  const parents: string[] = [];
  for (let i = 1; i < parts.length; i++) {
    parents.push(parts.slice(0, i).join("/"));
  }
  return parents;
}

export function isQaNodeDescendant(node: QaNode, targetId: string): boolean {
  return (node.children ?? []).some(
    (child) => child.node_id === targetId || isQaNodeDescendant(child, targetId),
  );
}

export function getQaNodeAncestors(nodes: QaNode[], targetId: string, ancestors: string[] = []): string[] | null {
  for (const node of nodes) {
    if (node.node_id === targetId) {
      return ancestors;
    }
    if (node.children && node.children.length > 0) {
      const result = getQaNodeAncestors(node.children, targetId, [...ancestors, node.node_id]);
      if (result) return result;
    }
  }
  return null;
}

/** 分類在樹上實際掛的上層；最上層或不在樹上時回 null。 */
export function getQaNodeParentId(nodes: QaNode[], targetId: string): string | null {
  const ancestors = getQaNodeAncestors(nodes, targetId);
  return ancestors && ancestors.length > 0 ? ancestors[ancestors.length - 1] : null;
}

/** 要讓某個分類看得到內容所需展開的路徑；null 代表快速問答最上層。 */
export function qaNodeExpandPaths(nodes: QaNode[], nodeId: string | null): string[] {
  if (!nodeId) return [QUICK_QA_TREE_PATH];
  const ancestors = getQaNodeAncestors(nodes, nodeId) ?? [];
  return [QUICK_QA_TREE_PATH, ...ancestors.map(qaTreeNodePath), qaTreeNodePath(nodeId)];
}

/* ── 批次操作 ── */

export interface BatchFailure {
  path: string;
  reason: string;
}

export interface BatchResult {
  succeeded: string[];
  failed: BatchFailure[];
}

const BATCH_SUMMARY_FAILURE_LIMIT = 5;

export function fileNameOf(path: string): string {
  return path.split("/").pop() || path;
}

export function parentDirOf(path: string): string {
  return path.split("/").slice(0, -1).join("/");
}

// 核心文件單檔也不能刪或移，批次一樣排除；QA 樹的虛擬節點不是檔案。
export function isBatchSelectableFile(node: TreeNode): boolean {
  return node.type === "file" && !node.virtual && !node.treeKind && !!node.doc && !node.doc.is_core;
}

export function collectBatchSelectableFiles(node: TreeNode): string[] {
  if (node.type === "file") {
    return isBatchSelectableFile(node) ? [node.path] : [];
  }
  if (node.virtual) return [];
  return node.children.flatMap(collectBatchSelectableFiles);
}

// 逐檔依序呼叫：後端搬移／刪除會排背景重建索引，同時打多支容易互相踩到。
export async function runBatchSequentially(
  paths: string[],
  action: (path: string) => Promise<unknown>,
  onProgress?: (done: number, total: number) => void,
): Promise<BatchResult> {
  const succeeded: string[] = [];
  const failed: BatchFailure[] = [];
  for (const [index, path] of paths.entries()) {
    try {
      await action(path);
      succeeded.push(path);
    } catch (error) {
      failed.push({ path, reason: error instanceof Error ? error.message : String(error) });
    }
    onProgress?.(index + 1, paths.length);
  }
  return { succeeded, failed };
}

export function formatBatchSummary(actionLabel: string, result: BatchResult, note?: string): string {
  let message = `${actionLabel}完成 ${result.succeeded.length} 個`;
  if (note) message += `，${note}`;
  if (result.failed.length === 0) return message;
  const listed = result.failed
    .slice(0, BATCH_SUMMARY_FAILURE_LIMIT)
    .map((failure) => `${fileNameOf(failure.path)}（${failure.reason}）`)
    .join("、");
  const rest = result.failed.length - BATCH_SUMMARY_FAILURE_LIMIT;
  return `${message}，${result.failed.length} 個失敗：${listed}${rest > 0 ? `，另有 ${rest} 個` : ""}`;
}
