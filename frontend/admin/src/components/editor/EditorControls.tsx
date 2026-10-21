import { useRef } from "react";

import { useBottomBarClearance } from "../../hooks/useBottomBarClearance";

export type EditorMode = "edit" | "preview" | "split";

const EDITOR_MODES: Array<{ mode: EditorMode; label: string }> = [
  { mode: "edit", label: "編輯" },
  { mode: "split", label: "並排" },
  { mode: "preview", label: "預覽" },
];

interface EditorModeSwitchProps {
  mode: EditorMode;
  onChange: (mode: EditorMode) => void;
}

export function EditorModeSwitch({ mode, onChange }: EditorModeSwitchProps) {
  return (
    <div className="flex shrink-0 overflow-hidden rounded-md border border-border bg-surface-raised" role="group" aria-label="編輯模式">
      {EDITOR_MODES.map((item) => (
        <button
          key={item.mode}
          type="button"
          onClick={() => onChange(item.mode)}
          aria-pressed={mode === item.mode}
          className={`whitespace-nowrap px-3 py-1.5 text-xs font-semibold transition-colors ${
            mode === item.mode
              ? "bg-border text-content"
              : "text-content-muted hover:bg-surface-sunken hover:text-content"
          }`}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

interface EditorSaveBarProps {
  hasUnsavedChanges: boolean;
  charCount: number;
  saving: boolean;
  canSave: boolean;
  saveLabel?: string;
  onDiscard: () => void;
  onSave: () => void;
}

/**
 * 編輯器底部的狀態與儲存列。
 *
 * 會把自己的高度登記成底部操作列，右下角的小助理就會往上讓，不會蓋住儲存鈕；
 * 窄畫面時狀態與按鈕各自換行。
 */
export function EditorSaveBar({
  hasUnsavedChanges,
  charCount,
  saving,
  canSave,
  saveLabel = "儲存",
  onDiscard,
  onSave,
}: EditorSaveBarProps) {
  const barRef = useRef<HTMLDivElement>(null);
  useBottomBarClearance(barRef);

  return (
    <div ref={barRef} className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 px-1 pt-2">
      <div className="flex items-center gap-2 whitespace-nowrap text-xs text-content-subtle">
        <span
          className={`h-2 w-2 rounded-full ${hasUnsavedChanges ? "animate-pulse bg-amber-500" : "bg-emerald-500"}`}
          aria-hidden="true"
        />
        {hasUnsavedChanges ? "尚未儲存" : "已儲存"}
        <span className="opacity-30" aria-hidden="true">•</span>
        {charCount.toLocaleString()} 字
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onDiscard}
          disabled={!hasUnsavedChanges}
          className="btn btn-ghost"
        >
          捨棄修改
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={saving || !canSave}
          className="btn btn-primary"
        >
          <span className="material-symbols-outlined text-[1.125rem]" aria-hidden="true">save</span>
          {saving ? "儲存中…" : saveLabel}
        </button>
      </div>
    </div>
  );
}
