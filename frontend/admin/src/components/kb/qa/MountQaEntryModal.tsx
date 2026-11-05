import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";

import type { QaNode } from "../../../hooks/useQaNodes";
import { errorMessage } from "../../../utils/errorMessage";
import { useModalDismiss } from "../useModalDismiss";
import { flattenCategories } from "./MoveQaNodeModal";

interface MountQaEntryModalProps {
  question: string;
  /** 正在編輯的分類，不能再放一次。 */
  currentNodeId: string;
  /** 已經放了這題的分類名稱。 */
  alreadyIn: string[];
  nodesTree: QaNode[];
  /** 失敗就丟錯，對話框會留著並寫出原因。 */
  onConfirm: (nodeId: string) => Promise<void>;
  onClose: () => void;
}

export default function MountQaEntryModal({
  question,
  currentNodeId,
  alreadyIn,
  nodesTree,
  onConfirm,
  onClose,
}: MountQaEntryModalProps) {
  const categories = useMemo(() => flattenCategories(nodesTree), [nodesTree]);
  const [selected, setSelected] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const dismiss = useModalDismiss(onClose, !saving);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    dialogRef.current?.querySelector<HTMLInputElement>('input[type="radio"]:not(:disabled)')?.focus();
    return () => previousFocus?.focus();
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onConfirm(selected);
    } catch (mountError) {
      setError(`沒有放成功：${errorMessage(mountError, "請再試一次。")}`);
      setSaving(false);
    }
  };

  const optionClass = (disabled: boolean) =>
    `flex items-center gap-2 py-2 pr-4 text-sm ${
      disabled
        ? "cursor-not-allowed text-content-subtle"
        : "cursor-pointer text-content hover:bg-surface-sunken"
    }`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      {...dismiss}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="mx-4 flex max-h-[70dvh] w-full max-w-md flex-col rounded-2xl border border-border bg-surface-raised shadow-2xl"
      >
        <div className="border-b border-border px-5 py-4">
          <h3 id={titleId} className="card-title break-words">
            把「{question}」也放到…
          </h3>
          <p className="mt-1 text-xs text-content-muted">
            放過去的是同一題，不是複製。之後改答案，每個分類都會一起改。
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <fieldset className="min-w-0 py-2">
              <legend className="sr-only">要放到哪個分類</legend>
              {categories.length === 0 && (
                <p className="px-5 py-2 text-sm text-content-muted">還沒有其他分類。</p>
              )}
              {categories.map(({ node: category, depth }) => {
                const isCurrent = category.node_id === currentNodeId;
                const hasIt = alreadyIn.includes(category.label);
                const disabled = isCurrent || hasIt;
                return (
                  <label
                    key={category.node_id}
                    className={optionClass(disabled)}
                    style={{ paddingLeft: `${1.25 + depth}rem` }}
                  >
                    <input
                      type="radio"
                      name={titleId}
                      value={category.node_id}
                      disabled={disabled}
                      checked={selected === category.node_id}
                      onChange={() => setSelected(category.node_id)}
                      className="shrink-0 accent-primary"
                    />
                    <span className="min-w-0 flex-1 truncate" title={category.label}>
                      {category.label}
                    </span>
                    {isCurrent && <span className="shrink-0 text-xs text-content-subtle">就是這個分類</span>}
                    {!isCurrent && hasIt && <span className="shrink-0 text-xs text-content-subtle">已經有這題</span>}
                  </label>
                );
              })}
            </fieldset>
          </div>

          {error && (
            <p role="alert" className="border-t border-border px-5 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-4">
            <button type="button" className="btn btn-ghost" disabled={saving} onClick={onClose}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={!selected || saving}>
              {saving ? "放進去中…" : "放到這裡"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
