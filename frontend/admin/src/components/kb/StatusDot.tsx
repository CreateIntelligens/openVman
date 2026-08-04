import type { KnowledgeDocumentSummary } from "../../api";

export default function StatusDot({ doc }: { doc: KnowledgeDocumentSummary }) {
  if (doc.is_indexed) {
    return (
      <span
        className="material-symbols-outlined shrink-0 text-[0.875rem] text-success"
        role="img"
        aria-label="已索引"
        title="已索引"
      >
        check_circle
      </span>
    );
  }
  if (doc.is_indexable) {
    return (
      <span
        className="material-symbols-outlined shrink-0 animate-pulse text-[0.875rem] text-warn"
        role="img"
        aria-label="待處理"
        title="待處理"
      >
        progress_activity
      </span>
    );
  }
  return (
    <span
      className="material-symbols-outlined shrink-0 text-[0.875rem] text-content-subtle"
      role="img"
      aria-label="已排除"
      title="已排除"
    >
      block
    </span>
  );
}
