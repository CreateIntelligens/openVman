import type { KnowledgeLanguage, QaAllQuestions, QaQuestionRow } from "../../../api/knowledge";
import type { QaNode } from "../../../hooks/useQaNodes";
import { categoryLanguage } from "../qa/languageCategories";
import { languageKey, NO_LANGUAGE } from "./allQuestions";

export function withTreeQuestionDetails(
  data: QaAllQuestions | null,
  nodes: QaNode[],
): QaQuestionRow[] {
  const byId = new Map<string, QaNode>();
  function index(nodesToIndex: QaNode[]) {
    for (const node of nodesToIndex) {
      byId.set(node.node_id, node);
      index(node.children ?? []);
    }
  }
  index(nodes);
  const categories = new Map(data?.categories.map((category) => [category.node_id, category]));
  return (data?.questions ?? []).map((row) => {
    const nodeId = row.category_ids[0];
    const entry = row.source.kind === "menu_only"
      ? byId.get(nodeId)?.qa_entries?.find((item) => !item.source_path && item.question === row.question)
      : undefined;
    return {
      ...row,
      language: row.language ?? categoryLanguage(categories.get(nodeId)?.path[0] ?? "") ?? null,
      hidden_in_file: entry?.hidden ?? row.hidden_in_file,
      image: entry?.image_id ?? row.image,
    };
  });
}

export function languageTree(nodes: QaNode[], rows: QaQuestionRow[], language: string): QaNode[] {
  if (!language) return nodes;
  const matchingNodeIds = new Set(rows.filter((row) => languageKey(row) === language).flatMap((row) => row.category_ids));
  function filter(branch: QaNode[], inherited?: KnowledgeLanguage, depth = 0): QaNode[] {
    return branch.flatMap((node) => {
      const declared = depth === 0 ? categoryLanguage(node.label) : inherited;
      const children = filter(node.children ?? [], declared, depth + 1);
      const visible = declared === language || matchingNodeIds.has(node.node_id) || children.length > 0
        || (language === NO_LANGUAGE && !declared && !node.qa_entries?.length);
      return visible ? [{ ...node, children }] : [];
    });
  }
  return filter(nodes);
}
