import { useEffect, useId, useState } from "react";

import type { QaNode } from "../../../hooks/useQaNodes";
import { useModalDismiss } from "../useModalDismiss";
import { moveToInsertion, useRowReorder } from "./rowReorder";
import { errorMessage } from "../../../utils/errorMessage";

type NodeUpdate = { label?: string; hidden?: boolean };
type NodeAction = Promise<unknown>;

interface VisibilityOrderModalProps {
  isOpen: boolean;
  onClose: () => void;
  parentNode: QaNode | null;
  nodesTree: QaNode[];
  onUpdateNode: (id: string, updates: NodeUpdate) => NodeAction;
  onReorderNode: (id: string, siblingIdsOrdered: string[]) => NodeAction;
  onRefresh: () => NodeAction;
}

const MOVE_BUTTON_CLASS =
  "flex h-8 w-8 items-center justify-center rounded-lg text-content-subtle transition-colors hover:bg-surface-sunken hover:text-content disabled:cursor-not-allowed disabled:opacity-30";

export default function VisibilityOrderModal({
  isOpen,
  onClose,
  parentNode,
  nodesTree,
  onUpdateNode,
  onReorderNode,
  onRefresh,
}: VisibilityOrderModalProps) {
  const [localNodes, setLocalNodes] = useState<QaNode[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const dismiss = useModalDismiss(onClose);
  const reorder = useRowReorder(localNodes.length, (from, insertAt) => {
    setLocalNodes((prev) => moveToInsertion(prev, from, insertAt));
  });

  useEffect(() => {
    if (isOpen) {
      const list = parentNode ? parentNode.children ?? [] : nodesTree;
      setLocalNodes([...list]);
      setError(null);
    }
  }, [isOpen, parentNode, nodesTree]);

  if (!isOpen) return null;

  const moveLocalNode = (index: number, offset: -1 | 1) => {
    const targetIndex = index + offset;
    if (targetIndex < 0 || targetIndex >= localNodes.length) return;

    const updated = [...localNodes];
    const temp = updated[index];
    updated[index] = updated[targetIndex];
    updated[targetIndex] = temp;
    setLocalNodes(updated);
  };

  const handleMoveUp = (index: number) => {
    moveLocalNode(index, -1);
  };

  const handleMoveDown = (index: number) => {
    moveLocalNode(index, 1);
  };

  const handleToggleHidden = (index: number) => {
    const updated = [...localNodes];
    updated[index] = {
      ...updated[index],
      hidden: !updated[index].hidden,
    };
    setLocalNodes(updated);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const originalNodes = parentNode ? parentNode.children ?? [] : nodesTree;
      const originalMap = new Map(originalNodes.map((n) => [n.node_id, n]));

      for (const node of localNodes) {
        const original = originalMap.get(node.node_id);
        if (original && original.hidden !== node.hidden) {
          await onUpdateNode(node.node_id, { hidden: node.hidden });
        }
      }

      const finalIdsOrdered = localNodes.map((n) => n.node_id);
      const originalIds = originalNodes.map((n) => n.node_id);
      const hasOrderChanged = finalIdsOrdered.some((id, idx) => id !== originalIds[idx]);

      if (hasOrderChanged && finalIdsOrdered.length > 0) {
        await onReorderNode(finalIdsOrdered[0], finalIdsOrdered);
      }

      await onRefresh();
      onClose();
    } catch (error: unknown) {
      setError(errorMessage(error, "儲存失敗，請再試一次。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      {...dismiss}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="mx-4 flex max-h-[80dvh] w-full max-w-xl flex-col rounded-2xl border border-border bg-surface-raised shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3 sm:px-6 sm:py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold text-content">調整順序與顯示</h2>
            <p className="mt-0.5 break-words text-sm font-medium text-content-muted">
              {parentNode ? parentNode.label : "最上層"}
            </p>
            <p className="mt-1 text-xs text-content-muted">
              拖曳整列或按上下箭頭調整順序。「已隱藏」的分類訪客在選單看不到，但 AI 回答時還是會用。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="關閉"
            className="shrink-0 rounded-lg p-1.5 text-content-muted transition-colors hover:bg-surface-sunken hover:text-content"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.25rem]">close</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 sm:p-4">
          {error && (
            <div role="alert" className="mb-3 rounded-lg border border-danger/20 bg-danger/5 p-3 text-sm text-danger">
              {error}
            </div>
          )}

          {localNodes.length === 0 ? (
            <div className="py-12 text-center text-sm text-content-muted">
              這一層還沒有子分類。
            </div>
          ) : (
            <ul className="divide-y divide-border rounded-xl border border-border">
              {localNodes.map((node, idx) => {
                const dropLine = reorder.dropLine(idx);
                return (
                  <li
                    key={node.node_id}
                    {...reorder.rowProps(idx)}
                    {...reorder.handleProps(idx)}
                    className={`relative flex cursor-grab flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 transition-colors hover:bg-surface-sunken/50 active:cursor-grabbing ${
                      reorder.isDragging(idx) ? "opacity-40" : ""
                    }`}
                  >
                    {dropLine && (
                      <span
                        aria-hidden="true"
                        className={`pointer-events-none absolute inset-x-0 h-0.5 bg-primary ${
                          dropLine === "before" ? "top-0" : "bottom-0"
                        }`}
                      />
                    )}
                    <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[1.125rem] text-content-subtle">
                      drag_indicator
                    </span>
                    <span className="w-5 shrink-0 text-right text-xs tabular-nums text-content-muted">
                      {idx + 1}
                    </span>
                    {/* 窄畫面名稱佔滿一行，按鈕換到下一行，不跟名稱搶寬度。 */}
                    <p className={`min-w-0 flex-1 basis-[calc(100%-3.5rem)] break-words text-sm font-medium text-content sm:basis-0 ${node.hidden ? "opacity-60" : ""}`}>
                      {node.label}
                    </p>
                    <div className="ml-auto flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => handleToggleHidden(idx)}
                        aria-label={node.hidden ? `${node.label}已隱藏，按一下改成顯示` : `${node.label}顯示中，按一下隱藏`}
                        className={`btn btn-ghost gap-1 px-2 py-1 text-xs ${node.hidden ? "bg-surface-sunken" : ""}`}
                      >
                        <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">
                          {node.hidden ? "visibility_off" : "visibility"}
                        </span>
                        {node.hidden ? "已隱藏" : "顯示中"}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleMoveUp(idx)}
                        disabled={idx === 0}
                        className={MOVE_BUTTON_CLASS}
                        aria-label={`上移 ${node.label}`}
                      >
                        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">arrow_upward</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleMoveDown(idx)}
                        disabled={idx === localNodes.length - 1}
                        className={MOVE_BUTTON_CLASS}
                        aria-label={`下移 ${node.label}`}
                      >
                        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">arrow_downward</span>
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border px-4 py-3 sm:px-6 sm:py-4">
          <button type="button" onClick={onClose} disabled={saving} className="btn btn-ghost">
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || localNodes.length === 0}
            className="btn btn-primary"
          >
            {saving && (
              <span aria-hidden="true" className="material-symbols-outlined animate-spin text-[1rem]">sync</span>
            )}
            {saving ? "儲存中…" : "儲存變更"}
          </button>
        </div>
      </div>
    </div>
  );
}
