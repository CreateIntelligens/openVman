import type { QaNode } from "../../../hooks/useQaNodes";

/**
 * 第一層分類叫這些名字，就是語言分類：匯入的同語言問答表會自動放進來，前台訪客選單
 * 也靠這個名字切換語言。要和 Brain 的 knowledge/qa_nodes.py 與前台
 * frontend/app/src/components/controls/quickQaText.ts 的 LANGUAGE_LABELS 一致，有測試比對。
 * 比對時忽略大小寫與前後空白。
 */
export const LANGUAGE_CATEGORY_LABELS: Record<string, string> = {
  "中文": "zh", "華語": "zh", "繁體中文": "zh",
  "english": "en",
  "español": "es", "espanol": "es",
  "日本語": "ja",
  "한국어": "ko",
};

export const LANGUAGE_CATEGORY_RENAME_WARNING =
  "這是語言分類：同語言的問答表會自動放進來，訪客選單也靠這個名字切換語言。改成別的名字後這兩件事都會失效。";

export function isLanguageCategoryLabel(label: string): boolean {
  return Object.prototype.hasOwnProperty.call(LANGUAGE_CATEGORY_LABELS, label.trim().toLowerCase());
}

/** 只有最上層才算：放在別的分類底下的「English」不會被當成語言分類。 */
export function isLanguageCategory(nodesTree: QaNode[], nodeId: string): boolean {
  const node = nodesTree.find((candidate) => candidate.node_id === nodeId);
  return !!node && isLanguageCategoryLabel(node.label);
}
