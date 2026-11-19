import type { KnowledgeDocumentSummary, QaCategorySummary } from "../../api/knowledge";
import type { QaNode } from "../../hooks/useQaNodes";
import { DOCUMENTS_ROOT_PATH, DOCUMENTS_SECTION_LABEL, fileNameOf, type TreeNode } from "./helpers";
import { isLanguageCategoryLabel } from "./qa/languageCategories";

/** 文件標題可能直接由檔名產生，不能拿它代替廠商畫面的文件名稱。 */
export function vendorDocumentLabels(documents: KnowledgeDocumentSummary[]): ReadonlyMap<string, string> {
  const ordered = [...documents].sort((a, b) =>
    (a.created_at ?? "").localeCompare(b.created_at ?? "") || a.path.localeCompare(b.path),
  );
  return new Map(ordered.map((document, index) => [document.path, `文件 ${index + 1}`]));
}

export function vendorDocumentLabel(path: string, labels?: ReadonlyMap<string, string>): string {
  return labels?.get(path) ?? "文件";
}

export function vendorFolderName(path: string): string {
  if (path === `${DOCUMENTS_ROOT_PATH}/notes`) return "自行建立";
  if (path === `${DOCUMENTS_ROOT_PATH}/qa`) return "問答文件";
  return fileNameOf(path);
}

export function vendorFolderLabel(path: string): string {
  if (!path || path === DOCUMENTS_ROOT_PATH) return `${DOCUMENTS_SECTION_LABEL}（最上層）`;
  const parts = path.split("/");
  if (!path.startsWith(`${DOCUMENTS_ROOT_PATH}/`)) return DOCUMENTS_SECTION_LABEL;
  return parts.slice(1).map((_, index) => vendorFolderName(parts.slice(0, index + 2).join("/"))).join(" › ");
}

export function vendorDocumentTree(node: TreeNode, labels?: ReadonlyMap<string, string>): TreeNode {
  if (node.virtual && node.treeKind !== "sections") return node;
  const name = node.treeKind || node.path === DOCUMENTS_ROOT_PATH
    ? node.name
    : node.type === "file" ? vendorDocumentLabel(node.path, labels) : vendorFolderName(node.path);
  return { ...node, name, children: node.children.map((child) => vendorDocumentTree(child, labels)) };
}

/** 從文件建立的分類會直接沿用檔名，只有這類名稱需要遮蔽。 */
export function vendorQaCategoryLabels(
  nodes: QaNode[],
  documentLabels?: ReadonlyMap<string, string>,
): ReadonlyMap<string, string> {
  const labels = new Map<string, string>();
  const visit = (branch: QaNode[]) => {
    for (const node of branch) {
      const file = node.qa_entries?.find((entry) => {
        if (!entry.source_path) return false;
        const basename = fileNameOf(entry.source_path);
        return node.label === basename || node.label === basename.replace(/\.[^.]+$/, "");
      });
      if (file && !isLanguageCategoryLabel(node.label) && !labels.has(node.node_id)) {
        const document = documentLabels?.get(file.source_path);
        labels.set(node.node_id, document ? `${document}的題目` : `匯入分類 ${labels.size + 1}`);
      }
      visit(node.children ?? []);
    }
  };
  visit(nodes);
  return labels;
}

export function relabelQaNodes(nodes: QaNode[], labels: ReadonlyMap<string, string>): QaNode[] {
  return nodes.map((node) => ({
    ...node,
    label: labels.get(node.node_id) ?? node.label,
    children: node.children && relabelQaNodes(node.children, labels),
  }));
}

export function relabelQaCategories(categories: QaCategorySummary[], labels: ReadonlyMap<string, string>): QaCategorySummary[] {
  const byId = new Map(categories.map((category) => [category.node_id, category]));
  return categories.map((category) => {
    const path = [...category.path];
    let current: QaCategorySummary | undefined = category;
    for (let index = path.length - 1; current && index >= 0; index -= 1) {
      path[index] = labels.get(current.node_id) ?? path[index];
      current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
    return { ...category, label: labels.get(category.node_id) ?? category.label, path };
  });
}
