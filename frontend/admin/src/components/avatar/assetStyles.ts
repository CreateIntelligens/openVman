import type { CSSProperties } from "react";

/** 三個資產分頁共用的版面與控制項樣式。 */

export const assetGridClassName =
  "grid min-w-0 shrink-0 grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4";

export const formRowClassName =
  "flex min-w-0 flex-col gap-3 md:flex-row md:flex-wrap";

export const fileRowClassName =
  "flex min-w-0 flex-col gap-4 md:flex-row md:flex-wrap md:items-center";

export const fileFieldClassName =
  "flex w-full min-w-0 flex-col gap-2 md:w-auto md:flex-1 md:flex-row md:items-center";

export const inputClassName = [
  "w-full min-w-0 md:w-auto md:flex-1 rounded border border-border",
  "bg-surface px-3 py-1.5 text-sm",
  "text-content outline-none focus:ring-2 focus:ring-primary",
].join(" ");

export const formPanelClassName = [
  "flex min-w-0 shrink-0 flex-col gap-3 rounded-lg border border-border bg-surface-raised p-4",
].join(" ");

export const assetCardClassName = [
  "flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-surface-raised",
].join(" ");

export const mediaPreviewClassName = "aspect-video w-full bg-surface-sunken";
export const cardBodyClassName = "flex min-w-0 flex-1 flex-col gap-1 p-3 [overflow-wrap:anywhere]";
export const cardActionsClassName = "flex flex-col gap-2 px-3 pb-3 md:flex-row";

export const primaryActionClassName = [
  "min-w-0 flex-1 whitespace-nowrap rounded bg-primary py-1 text-xs text-content-inverse transition-colors",
  "hover:bg-primary-600",
].join(" ");

export const secondaryActionClassName = [
  "min-w-0 flex-1 whitespace-nowrap rounded border border-border py-1 text-xs text-content-muted transition-colors",
  "hover:bg-surface-sunken",
].join(" ");

export const dangerActionClassName = [
  "min-w-0 flex-1 whitespace-nowrap rounded border border-red-200 py-1 text-xs text-red-600 transition-colors",
  "hover:bg-red-50 dark:border-red-900/50 dark:text-red-400 dark:hover:bg-red-900/20",
].join(" ");

export const uploadButtonClassName = [
  "w-full whitespace-nowrap md:ml-auto md:w-auto md:shrink-0 rounded-md bg-primary px-4 py-1.5 text-sm text-content-inverse",
  "font-medium transition-colors hover:bg-primary-600 disabled:opacity-50 shadow-sm",
].join(" ");

const filePickerBaseClassName = [
  "flex w-full min-w-0 cursor-pointer items-center whitespace-nowrap md:w-auto gap-1.5 rounded border border-dashed px-3 py-1.5",
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
