import { useEffect, useState } from "react";

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
      setError(errorMessage(error, "儲存變更失敗，請重試。"));
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
        className="bg-surface-raised border border-border rounded-2xl shadow-2xl w-full max-w-xl max-h-[80vh] flex flex-col mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[1.5rem]">
              sort
            </span>
            <div>
              <span className="text-base font-semibold text-content ">
                調整順序與可見性
              </span>
              <p className="text-xs text-content-muted mt-0.5">
                {parentNode ? parentNode.label : "最上層"}：拖曳整列或用箭頭調整順序
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-content-muted hover:text-content hover:bg-surface-sunken transition-colors"
          >
            <span className="material-symbols-outlined text-[1.25rem]">close</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm dark:bg-red-950/20 dark:border-red-900 dark:text-red-400">
              {error}
            </div>
          )}

          {localNodes.length === 0 ? (
            <div className="text-center py-12 text-content-subtle">
              該層級下尚無任何子節點。
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
                    className={`relative flex cursor-grab items-center gap-2 px-3 py-2 transition-colors hover:bg-surface-sunken/50 active:cursor-grabbing ${
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
                    <span className="w-5 shrink-0 text-right font-mono text-xs tabular-nums text-content-subtle">
                      {idx + 1}
                    </span>
                    <div className={`min-w-0 flex-1 ${node.hidden ? "opacity-60" : ""}`}>
                      <p className="truncate text-sm font-medium text-content" title={node.label}>{node.label}</p>
                      <p className="truncate font-mono text-xs text-content-subtle" title={node.node_id}>{node.node_id}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleToggleHidden(idx)}
                      className={`flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium whitespace-nowrap transition-colors ${
                        node.hidden
                          ? "bg-surface-sunken text-content-muted hover:bg-border"
                          : "bg-success/10 text-success hover:bg-success/20 dark:bg-success/20"
                      }`}
                    >
                      <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">
                        {node.hidden ? "visibility_off" : "visibility"}
                      </span>
                      {node.hidden ? "已隱藏" : "顯示中"}
                    </button>
                    <div className="flex shrink-0 items-center">
                      <button
                        type="button"
                        onClick={() => handleMoveUp(idx)}
                        disabled={idx === 0}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-content-subtle transition-colors hover:bg-surface-sunken hover:text-content disabled:opacity-30"
                        title="上移"
                        aria-label={`上移 ${node.label}`}
                      >
                        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">arrow_upward</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleMoveDown(idx)}
                        disabled={idx === localNodes.length - 1}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-content-subtle transition-colors hover:bg-surface-sunken hover:text-content disabled:opacity-30"
                        title="下移"
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

        <div className="px-6 py-4 border-t border-border flex items-center justify-end gap-3 shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm font-medium text-content-muted hover:text-content hover:bg-surface-sunken transition-colors"
            disabled={saving}
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving || localNodes.length === 0}
            className="px-5 py-2 rounded-xl bg-primary text-sm font-semibold text-white hover:bg-primary-600 disabled:opacity-30 transition-all flex items-center gap-1.5 shadow-md shadow-primary/10"
          >
            {saving ? (
              <>
                <span className="material-symbols-outlined text-[1.1rem] animate-spin">
                  sync
                </span>
                儲存中...
              </>
            ) : (
              <>
                <span className="material-symbols-outlined text-[1.1rem]">save</span>
                儲存變更
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
