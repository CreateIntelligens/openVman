import { useEffect, useState } from "react";

import type { QaNode } from "../../../hooks/useQaNodes";
import { useModalDismiss } from "../useModalDismiss";
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
        className="bg-surface-raised border border-border rounded-2xl shadow-2xl w-full max-w-3xl max-h-[80vh] flex flex-col mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[1.5rem]">
              sort
            </span>
            <div>
              <span className="text-base font-semibold text-content ">
                批次調整可見性與順序
              </span>
              <p className="text-xs text-content-muted mt-0.5">
                於父節點：{parentNode ? parentNode.label : "根節點目錄"}
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

        <div className="flex-1 overflow-y-auto p-6">
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
            <div className="border border-border rounded-xl overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface dark:bg-surface/50 border-b border-border text-xs font-semibold text-content-muted">
                    <th className="py-3 px-4 text-center whitespace-nowrap">原始順序</th>
                    <th className="py-3 px-4 whitespace-nowrap">識別 ID</th>
                    <th className="py-3 px-4 whitespace-nowrap">節點名稱</th>
                    <th className="py-3 px-4 text-center whitespace-nowrap">顯示狀態</th>
                    <th className="py-3 px-4 text-center whitespace-nowrap">順序調整</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border text-sm">
                  {localNodes.map((node, idx) => (
                    <tr
                      key={node.node_id}
                      className="hover:bg-surface-sunken/50 text-content-muted transition-colors"
                    >
                      <td className="py-3.5 px-4 text-center text-xs font-mono text-content-subtle">
                        {idx + 1}
                      </td>
                      <td className="py-3.5 px-4 font-mono text-xs">
                        {node.node_id}
                      </td>
                      <td className="py-3.5 px-4 font-medium">
                        {node.label}
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="flex justify-center">
                          <button
                            onClick={() => handleToggleHidden(idx)}
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors ${
                              node.hidden
                                ? "bg-surface-sunken hover:bg-border text-content-muted "
                                : "bg-success/10 text-success hover:bg-success/20 dark:bg-success/20 dark:text-success"
                            }`}
                          >
                            <span className="material-symbols-outlined text-[1rem]">
                              {node.hidden ? "visibility_off" : "visibility"}
                            </span>
                            {node.hidden ? "已隱藏" : "顯示中"}
                          </button>
                        </div>
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="flex items-center justify-center gap-1.5">
                          <button
                            onClick={() => handleMoveUp(idx)}
                            disabled={idx === 0}
                            className="w-8 h-8 shrink-0 flex items-center justify-center rounded-lg hover:bg-surface-sunken text-content-muted hover:text-content disabled:opacity-30 disabled:pointer-events-none transition-colors"
                            title="上移"
                          >
                            <span className="material-symbols-outlined text-[1.25rem]">
                              arrow_upward
                            </span>
                          </button>
                          <button
                            onClick={() => handleMoveDown(idx)}
                            disabled={idx === localNodes.length - 1}
                            className="w-8 h-8 shrink-0 flex items-center justify-center rounded-lg hover:bg-surface-sunken text-content-muted hover:text-content disabled:opacity-30 disabled:pointer-events-none transition-colors"
                            title="下移"
                          >
                            <span className="material-symbols-outlined text-[1.25rem]">
                              arrow_downward
                            </span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
