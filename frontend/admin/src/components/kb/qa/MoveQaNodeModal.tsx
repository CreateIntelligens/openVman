import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";

import type { QaNode } from "../../../hooks/useQaNodes";
import { errorMessage } from "../../../utils/errorMessage";
import { isQaNodeDescendant } from "../helpers";
import { useModalDismiss } from "../useModalDismiss";

const TOP_LEVEL_VALUE = "__top_level__";

interface MoveQaNodeModalProps {
  node: QaNode;
  nodesTree: QaNode[];
  /** parentId 是 null 代表移到最上層；失敗就丟錯，對話框會留著並寫出原因。 */
  onConfirm: (parentId: string | null) => void | Promise<void>;
  onClose: () => void;
}

export interface FlatCategory {
  node: QaNode;
  depth: number;
}

// 同一分類可能掛在多個上層，攤平時只留第一次出現的位置。
export function flattenCategories(
  nodes: QaNode[],
  depth = 0,
  seen = new Set<string>(),
): FlatCategory[] {
  return nodes.flatMap((node) => {
    if (seen.has(node.node_id)) return [];
    seen.add(node.node_id);
    return [
      { node, depth },
      ...flattenCategories(node.children ?? [], depth + 1, seen),
    ];
  });
}

export default function MoveQaNodeModal({
  node,
  nodesTree,
  onConfirm,
  onClose,
}: MoveQaNodeModalProps) {
  const categories = useMemo(() => flattenCategories(nodesTree), [nodesTree]);
  // 上層已被刪掉的分類在樹上算最上層，目前位置要跟畫面一致。
  const currentParentIds = (node.parent_ids ?? []).filter((id) =>
    categories.some(({ node: category }) => category.node_id === id),
  );
  const currentValue = currentParentIds[0] ?? TOP_LEVEL_VALUE;
  const [selected, setSelected] = useState(currentValue);
  const [moving, setMoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const dismiss = useModalDismiss(onClose, !moving);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    dialogRef.current
      ?.querySelector<HTMLInputElement>('input[type="radio"]:checked')
      ?.focus();
    return () => previousFocus?.focus();
  }, []);

  const isCurrent = (value: string) =>
    value === TOP_LEVEL_VALUE
      ? currentParentIds.length === 0
      : currentParentIds.includes(value);
  // 掛在多個上層的分類選了其中一個仍算有變化：移動後只會留下選的這一個。
  const canConfirm = !moving &&
    (selected !== currentValue || currentParentIds.length > 1);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canConfirm) return;
    setMoving(true);
    setError(null);
    try {
      await onConfirm(selected === TOP_LEVEL_VALUE ? null : selected);
    } catch (moveError) {
      setError(`沒有移動成功：${errorMessage(moveError, "請再試一次。")}`);
      setMoving(false);
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
            把「{node.label}」移到…
          </h3>
          <p className="mt-1 text-xs text-content-muted">
            選一個新位置，這個分類和它底下的內容會一起搬過去。
          </p>
        </div>

        {/* 用 form：在選項上按 Enter 就能確認。 */}
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          {/* 捲動放在外層：Chromium 的 fieldset 不會裁切自己的內容，分類一多清單就畫到對話框外面。 */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <fieldset className="min-w-0 py-2">
              <legend className="sr-only">新位置</legend>
              <label className={optionClass(false)} style={{ paddingLeft: "1.25rem" }}>
                <input
                  type="radio"
                  name={titleId}
                  value={TOP_LEVEL_VALUE}
                  checked={selected === TOP_LEVEL_VALUE}
                  onChange={() => setSelected(TOP_LEVEL_VALUE)}
                  className="shrink-0 accent-primary"
                />
                <span className="min-w-0 flex-1 truncate">最上層</span>
                {isCurrent(TOP_LEVEL_VALUE) && (
                  <span className="shrink-0 text-xs text-content-subtle">目前位置</span>
                )}
              </label>

              {categories.map(({ node: category, depth }) => {
                const isSelf = category.node_id === node.node_id;
                const isDescendant = isQaNodeDescendant(node, category.node_id);
                const disabled = isSelf || isDescendant;
                return (
                  <label
                    key={category.node_id}
                    className={optionClass(disabled)}
                    style={{ paddingLeft: `${1.25 + (depth + 1) * 1}rem` }}
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
                    {category.hidden && (
                      <span className="shrink-0 text-xs text-content-subtle">已隱藏</span>
                    )}
                    {isCurrent(category.node_id) && (
                      <span className="shrink-0 text-xs text-content-subtle">目前位置</span>
                    )}
                    {isSelf && (
                      <span className="shrink-0 text-xs text-content-subtle">就是這個分類</span>
                    )}
                    {isDescendant && (
                      <span className="shrink-0 text-xs text-content-subtle">在這個分類底下</span>
                    )}
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
            <button
              type="button"
              className="btn btn-ghost"
              disabled={moving}
              onClick={onClose}
            >
              取消
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!canConfirm}
            >
              {moving ? "移動中…" : "移到這裡"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
