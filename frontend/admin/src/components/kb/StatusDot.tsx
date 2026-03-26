import type { KnowledgeDocumentSummary } from "../../api";

export default function StatusDot({ doc }: { doc: KnowledgeDocumentSummary }) {
  if (doc.is_indexed) {
    return <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/80 shrink-0" title="已索引" />;
  }
  if (doc.is_indexable) {
    return <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse shrink-0" title="待處理" />;
  }
  return <span className="w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0" title="已排除" />;
}
