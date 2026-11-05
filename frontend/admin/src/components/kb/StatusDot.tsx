import type { KnowledgeDocumentSummary } from "../../api";

export type DocumentStatusLabel = "已停用" | "可被搜尋" | "處理中" | "不會被搜尋";

type DocumentStatusFields = Pick<
  KnowledgeDocumentSummary,
  "enabled" | "is_indexed" | "is_indexable"
>;

/** 文件狀態的完整文字。停用優先：停用的文件就算還在索引裡，AI 也不會用到。 */
export function documentStatusLabel(doc: DocumentStatusFields): DocumentStatusLabel {
  if (doc.enabled === false) return "已停用";
  if (doc.is_indexed) return "可被搜尋";
  if (doc.is_indexable) return "處理中";
  return "不會被搜尋";
}

const ATTENTION_STATUS: Partial<
  Record<DocumentStatusLabel, { icon: string; className: string }>
> = {
  已停用: { icon: "pause_circle", className: "text-content-subtle" },
  處理中: { icon: "progress_activity", className: "text-warn" },
  不會被搜尋: { icon: "block", className: "text-content-subtle" },
};

/** 正常的文件不顯示東西，樹上一整排綠勾只是噪音；要留意的狀態才寫出來。 */
export default function StatusDot({ doc }: { doc: DocumentStatusFields }) {
  const label = documentStatusLabel(doc);
  const status = ATTENTION_STATUS[label];
  if (!status) return null;

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap text-xs ${status.className}`}
    >
      <span
        aria-hidden="true"
        className={`material-symbols-outlined text-[0.875rem] ${
          label === "處理中" ? "animate-spin" : ""
        }`}
      >
        {status.icon}
      </span>
      {label}
    </span>
  );
}
