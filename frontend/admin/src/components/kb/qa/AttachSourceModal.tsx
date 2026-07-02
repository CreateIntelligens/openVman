import { useEffect, useMemo, useState } from "react";

import { fetchKnowledgeBaseDocuments, type KnowledgeDocumentSummary } from "../../../api";
import type { QaNode } from "../../../hooks/useQaNodes";
import { useModalDismiss } from "../useModalDismiss";
import { errorMessage } from "../../../utils/errorMessage";

interface AttachSourceModalProps {
  open: boolean;
  node: QaNode | null;
  onAttach: (nodeId: string, path: string) => Promise<unknown>;
  onDetach: (nodeId: string, path: string) => Promise<unknown>;
  onClose: () => void;
}

export default function AttachSourceModal({
  open,
  node,
  onAttach,
  onDetach,
  onClose,
}: AttachSourceModalProps) {
  const { onPointerDown, onPointerUp } = useModalDismiss(onClose);

  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchKnowledgeBaseDocuments()
      .then((res) => {
        if (cancelled) return;
        setDocuments(res.documents.filter((doc) => doc.source_type === "qa"));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(errorMessage(err, "無法取得問答文件清單"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const attachedPaths = useMemo(
    () => new Set((node?.qa_entries ?? []).map((entry) => entry.source_path)),
    [node],
  );

  if (!open || !node) return null;

  const handleToggle = async (doc: KnowledgeDocumentSummary) => {
    const attached = attachedPaths.has(doc.path);
    setBusyPath(doc.path);
    setError(null);
    try {
      if (attached) {
        await onDetach(node.node_id, doc.path);
      } else {
        await onAttach(node.node_id, doc.path);
      }
    } catch (err: unknown) {
      setError(errorMessage(err, attached ? "卸載來源失敗" : "掛載來源失敗"));
    } finally {
      setBusyPath(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
    >
      <div className="w-full max-w-2xl max-h-[85%] flex flex-col rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-2xl outline-none transition-all">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-white">掛載問答來源</h3>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              節點：<span className="font-semibold text-slate-700 dark:text-slate-300">{node.label}</span>（{node.node_id}）
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="關閉"
          >
            <span className="material-symbols-outlined text-[1.25rem]">close</span>
          </button>
        </div>

        {error && (
          <div className="mt-3 flex items-start gap-2 rounded-lg bg-danger/5 text-danger p-3 text-xs border border-danger/20">
            <span className="material-symbols-outlined text-[1.125rem] shrink-0">error</span>
            <div className="whitespace-pre-wrap">{error}</div>
          </div>
        )}

        <div className="mt-4 flex-1 min-h-0 overflow-y-auto rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-xs text-slate-500">
              <span className="material-symbols-outlined animate-spin mr-2 text-primary text-[1.25rem]">sync</span>
              正在載入問答文件...
            </div>
          ) : documents.length === 0 ? (
            <div className="py-10 text-center text-xs text-slate-400 dark:text-slate-500">
              尚無任何問答文件。請先在「文件」分頁上傳 QA CSV 並採納上傳。
            </div>
          ) : (
            documents.map((doc) => {
              const attached = attachedPaths.has(doc.path);
              const busy = busyPath === doc.path;
              return (
                <div key={doc.path} className="flex items-center gap-3 px-4 py-3">
                  <span className="material-symbols-outlined text-[1.125rem] text-primary shrink-0">quiz</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">
                      {doc.title || doc.path}
                    </p>
                    <p className="text-[0.7rem] font-mono text-slate-400 dark:text-slate-500 truncate">{doc.path}</p>
                  </div>
                  {attached && (
                    <span className="shrink-0 px-2 py-0.5 text-[0.7rem] font-bold text-success bg-success/10 border border-success/25 rounded-md">
                      掛載中
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => handleToggle(doc)}
                    disabled={busy}
                    className={`shrink-0 inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50 ${
                      attached
                        ? "border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-danger hover:border-danger/40 hover:bg-danger/5"
                        : "bg-primary text-white hover:bg-primary/90"
                    }`}
                  >
                    {busy ? (
                      <span className="material-symbols-outlined text-[1rem] animate-spin">sync</span>
                    ) : (
                      <span className="material-symbols-outlined text-[1rem]">
                        {attached ? "link_off" : "add_link"}
                      </span>
                    )}
                    {attached ? "卸載" : "掛載"}
                  </button>
                </div>
              );
            })
          )}
        </div>

        <div className="mt-5 flex items-center justify-end">
          <button
            onClick={onClose}
            className="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-2 text-sm text-slate-500 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white transition-colors"
          >
            關閉
          </button>
        </div>
      </div>
    </div>
  );
}
