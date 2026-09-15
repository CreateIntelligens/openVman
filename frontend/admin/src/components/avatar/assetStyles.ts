import type { CSSProperties } from "react";

/** 三個資產分頁共用的版面與控制項樣式。 */

export const assetGridStyle = {
  gridTemplateColumns: "repeat(auto-fill, minmax(16rem, 1fr))",
};

export const inputClassName = [
  "flex-1 min-w-0 rounded border border-border",
  "bg-surface px-3 py-1.5 text-sm",
  "text-content outline-none focus:ring-2 focus:ring-primary",
].join(" ");

export const formPanelClassName = [
  "flex flex-col gap-3 rounded-lg border border-border bg-surface-raised p-4",
].join(" ");

export const assetCardClassName = [
  "flex flex-col overflow-hidden rounded-lg border border-border bg-surface-raised",
].join(" ");

export const mediaPreviewClassName = "aspect-video w-full bg-surface-sunken";
export const cardBodyClassName = "flex flex-1 flex-col gap-1 p-3";
export const cardActionsClassName = "flex gap-2 px-3 pb-3";

export const primaryActionClassName = [
  "flex-1 rounded bg-primary py-1 text-xs text-content-inverse transition-colors",
  "hover:bg-primary-600",
].join(" ");

export const secondaryActionClassName = [
  "flex-1 rounded border border-border py-1 text-xs text-content-muted transition-colors",
  "hover:bg-surface-sunken",
].join(" ");

export const dangerActionClassName = [
  "flex-1 rounded border border-red-200 py-1 text-xs text-red-600 transition-colors",
  "hover:bg-red-50 dark:border-red-900/50 dark:text-red-400 dark:hover:bg-red-900/20",
].join(" ");

export const uploadButtonClassName = [
  "ml-auto rounded-md bg-primary px-4 py-1.5 text-sm text-content-inverse",
  "font-medium transition-colors hover:bg-primary-600 disabled:opacity-50 shadow-sm",
].join(" ");

const filePickerBaseClassName = [
  "flex cursor-pointer items-center gap-1.5 rounded border border-dashed px-3 py-1.5",
  "text-xs transition-all",
].join(" ");

const filePickerSelectedClassName = [
  "border-primary bg-primary-50/30 text-primary-600 dark:text-primary",
].join(" ");

const filePickerEmptyClassName = [
  "border-border-strong bg-surface text-content-muted hover:bg-surface-sunken",
  "dark:bg-surface-sunken",
].join(" ");

export function filePickerClassName(fileName: string): string {
  return [
    filePickerBaseClassName,
    fileName ? filePickerSelectedClassName : filePickerEmptyClassName,
  ].join(" ");
}

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
