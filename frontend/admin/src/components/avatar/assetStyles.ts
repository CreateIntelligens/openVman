/* Hallmark · component: asset upload forms · genre: modern-minimal · theme: project tokens (contracts/frontend-theme.css)
 * states: default · hover · focus · active · disabled · loading · error · success
 * pre-emit critique: P4 H4 E4 S4 R4 V-（元件範圍，不輪替）
 */
import type { CSSProperties } from "react";

/** 三個資產分頁共用的版面與控制項樣式。 */

export const assetGridClassName =
  "grid min-w-0 shrink-0 grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4";

/** 新增素材的卡片：標題、左邊檔案、右邊欄位與送出。 */
export const uploadCardClassName = "card flex min-w-0 shrink-0 flex-col gap-4 p-4 md:p-5";
export const uploadHeadingClassName = "text-base font-semibold text-content";
export const uploadLeadClassName = "text-sm text-content-muted";
export const uploadGridClassName = [
  "grid min-w-0 gap-4",
  "md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] md:gap-6",
].join(" ");
export const uploadFieldsClassName = "flex min-w-0 flex-col gap-3";
export const submitButtonClassName = "btn btn-primary w-full sm:w-auto sm:self-start";

/** 清單上方的標題列：名稱與數量。 */
export const listHeadingClassName = "flex min-w-0 items-baseline gap-2 text-sm font-semibold text-content";

export const assetCardClassName = [
  "flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-surface-raised",
].join(" ");

export const mediaPreviewClassName = "aspect-video w-full bg-surface-sunken";
export const cardBodyClassName = "flex min-w-0 flex-1 flex-col gap-1 p-3 [overflow-wrap:anywhere]";
export const cardActionsClassName = "flex flex-col gap-2 px-3 pb-3 md:flex-row";

const actionFocusClassName =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1";

export const primaryActionClassName = [
  "min-w-0 flex-1 whitespace-nowrap rounded bg-primary py-1 text-xs text-content-inverse transition-colors",
  "hover:bg-primary-600",
  actionFocusClassName,
].join(" ");

export const secondaryActionClassName = [
  "min-w-0 flex-1 whitespace-nowrap rounded border border-border py-1 text-xs text-content-muted transition-colors",
  "hover:bg-surface-sunken",
  actionFocusClassName,
].join(" ");

export const dangerActionClassName = [
  "min-w-0 flex-1 whitespace-nowrap rounded border border-red-200 py-1 text-xs text-red-600 transition-colors",
  "hover:bg-red-50 dark:border-red-900/50 dark:text-red-400 dark:hover:bg-red-900/20",
  actionFocusClassName,
].join(" ");

// 透明素材放在棋盤格上，才看得出哪裡是去背、舞台背景會從哪裡透出來。
export const checkerboardStyle: CSSProperties = {
  backgroundColor: "rgb(var(--color-surface-raised))",
  backgroundImage: [
    "linear-gradient(45deg, rgb(var(--color-border)) 25%, transparent 25%)",
    "linear-gradient(-45deg, rgb(var(--color-border)) 25%, transparent 25%)",
    "linear-gradient(45deg, transparent 75%, rgb(var(--color-border)) 75%)",
    "linear-gradient(-45deg, transparent 75%, rgb(var(--color-border)) 75%)",
  ].join(", "),
  backgroundSize: "1rem 1rem",
  backgroundPosition: "0 0, 0 0.5rem, 0.5rem -0.5rem, -0.5rem 0",
};

export const hiddenSnapshotFrameStyle: CSSProperties = {
  position: "absolute",
  left: "-62.5rem",
  top: "-62.5rem",
  width: "25rem",
  height: "31.25rem",
  pointerEvents: "none",
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
