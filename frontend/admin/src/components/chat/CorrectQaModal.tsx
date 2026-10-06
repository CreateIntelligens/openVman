import { useEffect, useMemo, useState } from "react";

import { useQaNodes, type MergedQaItem, type QaNode } from "../../hooks/useQaNodes";
import { errorMessage } from "../../utils/errorMessage";
import { useModalDismiss } from "../useModalDismiss";

interface CorrectQaModalProps {
  open: boolean;
  question: string;
  answer: string;
  onClose: () => void;
}

interface NodeOption {
  nodeId: string;
  label: string;
}

// 問答樹是 DAG：同一節點可能掛在多個父節點下，攤平時只留第一次出現的路徑。
export function flattenQaNodeOptions(nodes: QaNode[]): NodeOption[] {
  const options: NodeOption[] = [];
  const seen = new Set<string>();
  const walk = (list: QaNode[], prefix: string) => {
    for (const node of list) {
      const name = node.label || node.node_id;
      const path = prefix ? `${prefix} / ${name}` : name;
      if (!seen.has(node.node_id)) {
        seen.add(node.node_id);
        options.push({
          nodeId: node.node_id,
          label: node.hidden ? `${path}（隱藏）` : path,
        });
      }
      walk(node.children ?? [], path);
    }
  };
  walk(nodes, "");
  return options;
}

// 同題重存就地改答案，不另開重複題；新題併進這個節點既有的手動修正檔，
// 避免每修一題就多一個 manual_*.md。
export function applyCorrection(
  existing: MergedQaItem[],
  nodeId: string,
  correction: { q: string; a: string; hidden: boolean },
  now = Date.now(),
): MergedQaItem[] {
  const rows: MergedQaItem[] = existing.map(({ index: _index, ...item }) => item);
  const matchIndex = rows.findIndex((row) => row.q.trim() === correction.q);
  if (matchIndex >= 0) {
    return rows.map((row, i) => (i === matchIndex ? { ...row, a: correction.a } : row));
  }
  const manualPrefix = `knowledge/qa/manual_${nodeId}_`;
  const manualSource = [...rows]
    .reverse()
    .find((row) => row.source_file.startsWith(manualPrefix) && row.source_file.endsWith(".md"))
    ?.source_file;
  return [
    ...rows,
    {
      q: correction.q,
      a: correction.a,
      img: "",
      url: "",
      source_file: manualSource ?? `${manualPrefix}${now}.md`,
      hidden: correction.hidden,
    },
  ];
}

export default function CorrectQaModal({ open, question, answer, onClose }: CorrectQaModalProps) {
  const { nodesTree, loading, error: treeError, fetchTree, fetchMergedQa, saveMergedQa } = useQaNodes();
  const { onPointerDown, onPointerUp } = useModalDismiss(onClose, open);

  const [q, setQ] = useState(question);
  const [a, setA] = useState(answer);
  const [nodeId, setNodeId] = useState("");
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedLabel, setSavedLabel] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setQ(question);
    setA(answer);
    setVisible(false);
    setSaving(false);
    setError(null);
    setSavedLabel(null);
    fetchTree().catch(() => undefined);
  }, [open, question, answer, fetchTree]);

  const options = useMemo(() => flattenQaNodeOptions(nodesTree), [nodesTree]);

  // 保留同一個頁面裡上次選的節點，連續修好幾題時不用每次重選。
  useEffect(() => {
    if (options.length > 0 && !options.some((option) => option.nodeId === nodeId)) {
      setNodeId(options[0].nodeId);
    }
  }, [options, nodeId]);

  if (!open) return null;

  const trimmedQ = q.trim();
  const trimmedA = a.trim();
  const canSave = Boolean(trimmedQ && trimmedA && nodeId) && !saving;
  const selectedLabel = options.find((option) => option.nodeId === nodeId)?.label ?? nodeId;

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const existing = await fetchMergedQa(nodeId);
      const rows = applyCorrection(existing, nodeId, { q: trimmedQ, a: trimmedA, hidden: !visible });
      await saveMergedQa(nodeId, rows);
      setSavedLabel(selectedLabel);
    } catch (err: unknown) {
      setError(errorMessage(err, "儲存問答失敗"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="correct-qa-title"
        className="flex max-h-[85%] w-full max-w-2xl flex-col rounded-2xl border border-border bg-surface-raised p-6 shadow-2xl"
      >
        <div className="flex shrink-0 items-start justify-between gap-3">
          <div>
            <h3 id="correct-qa-title" className="card-title">修正成 QA</h3>
            <p className="mt-1 text-xs text-content-muted">
              把正確答案存進問答知識庫，重建索引後下一輪對話就會用到。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-content-subtle transition-colors hover:bg-surface-sunken hover:text-content"
            title="關閉"
          >
            <span className="material-symbols-outlined text-[1.25rem]">close</span>
          </button>
        </div>

        {savedLabel !== null ? (
          <div className="mt-5 flex flex-col gap-4">
            <div role="status" className="flex items-start gap-2 rounded-lg border border-success/20 bg-success/5 p-3 text-sm text-success">
              <span className="material-symbols-outlined shrink-0 text-[1.125rem]">check_circle</span>
              <span>{`已存入「${savedLabel}」。知識庫會在背景重建索引，幾秒後重新提問即可驗證。`}</span>
            </div>
            <div className="flex justify-end">
              <button type="button" onClick={onClose} className="btn btn-primary">關閉</button>
            </div>
          </div>
        ) : (
          <>
            {(error || treeError) && (
              <div role="alert" className="mt-3 flex shrink-0 items-start gap-2 rounded-lg border border-danger/20 bg-danger/5 p-3 text-xs text-danger">
                <span className="material-symbols-outlined shrink-0 text-[1.125rem]">error</span>
                <div className="whitespace-pre-wrap">{error ?? treeError}</div>
              </div>
            )}

            <div className="mt-4 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
              <label className="block text-sm font-medium text-content">
                問題
                <textarea
                  value={q}
                  onChange={(event) => setQ(event.target.value)}
                  rows={2}
                  className="input mt-1.5 resize-none"
                />
              </label>
              <label className="block text-sm font-medium text-content">
                正確答案
                <textarea
                  value={a}
                  onChange={(event) => setA(event.target.value)}
                  rows={8}
                  className="input mt-1.5 resize-y"
                />
              </label>
              <label className="block text-sm font-medium text-content">
                存到問答節點
                <select
                  value={nodeId}
                  onChange={(event) => setNodeId(event.target.value)}
                  disabled={loading || options.length === 0}
                  className="input mt-1.5"
                >
                  {options.map((option) => (
                    <option key={option.nodeId} value={option.nodeId}>{option.label}</option>
                  ))}
                </select>
              </label>
              {!loading && !treeError && options.length === 0 && (
                <p className="text-xs text-content-muted">
                  這個專案還沒有問答節點，請先到知識庫的「快速問答」建立節點。
                </p>
              )}
              <label className="inline-flex cursor-pointer select-none items-center gap-1.5 text-xs text-content-muted">
                <input
                  type="checkbox"
                  checked={visible}
                  onChange={(event) => setVisible(event.target.checked)}
                  className="rounded border-border-strong"
                />
                新增時顯示為預設問題按鈕（不勾也會進知識庫；已有同題時只更新答案）
              </label>
            </div>

            <div className="mt-5 flex shrink-0 justify-end gap-3">
              <button type="button" onClick={onClose} disabled={saving} className="btn btn-ghost">
                取消
              </button>
              <button
                type="button"
                onClick={() => { void handleSave(); }}
                disabled={!canSave}
                className="btn btn-primary"
              >
                <span className={`material-symbols-outlined text-[1.1rem] ${saving ? "animate-spin" : ""}`}>
                  {saving ? "sync" : "save"}
                </span>
                {saving ? "儲存中..." : "儲存"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
