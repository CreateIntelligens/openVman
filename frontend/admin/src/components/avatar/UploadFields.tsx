import { useEffect, useId, useState } from "react";
import type { DragEvent, ReactNode } from "react";

import Select from "../Select";
import { checkerboardStyle } from "./assetStyles";
import {
  acceptList,
  checkFile,
  formatFileSize,
  isImageFile,
  isVideoFile,
  type FileKind,
} from "./uploadRules";

type ProjectOption = { project_id: string; label: string };

const fieldLabelClassName = "text-sm font-medium text-content";
const fieldHintClassName = "text-xs text-content-subtle";

type TextFieldProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  placeholder?: string;
  disabled?: boolean;
  mono?: boolean;
};

export function TextField({
  label,
  value,
  onChange,
  hint,
  placeholder,
  disabled,
  mono,
}: TextFieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className={fieldLabelClassName}>
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onChange={(e) => onChange(e.target.value)}
        className={`input ${mono ? "font-mono" : ""}`}
        autoComplete="off"
        spellCheck={false}
      />
      {hint && (
        <p id={hintId} className={fieldHintClassName}>
          {hint}
        </p>
      )}
    </div>
  );
}

type ScopeFieldProps = {
  projects?: ProjectOption[];
  value: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
};

/** 素材歸屬：全域或某個專案專屬。沒有專案可選時整欄不顯示。 */
export function ScopeField({ projects, value, onChange, disabled }: ScopeFieldProps) {
  if (!projects || projects.length === 0 || !onChange) return null;
  const options = [
    { value: "", label: "全域（所有專案可用）" },
    ...projects.map((p) => ({ value: p.project_id, label: `專案專屬：${p.label || p.project_id}` })),
  ];
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className={fieldLabelClassName}>可用範圍</span>
      <Select
        value={value}
        options={options}
        onChange={onChange}
        disabled={disabled}
        ariaLabel="可用範圍"
      />
    </div>
  );
}

type FileDropFieldProps = {
  /** 欄位上方的可見名稱。 */
  label: string;
  /** 檔案輸入框的無障礙名稱；不給就用 label。 */
  inputLabel?: string;
  kinds: readonly FileKind[];
  file: File | null;
  onChange: (file: File | null) => void;
  /** 格式與上限，顯示在欄位下方。 */
  hint: ReactNode;
  /** 空白時的動作字樣，例如「選擇影片或圖片」。 */
  chooseText: string;
  icon: string;
  disabled?: boolean;
  optional?: boolean;
  /** media：大框，選好後顯示圖片或影片預覽；compact：一行。 */
  variant?: "media" | "compact";
};

function useObjectUrl(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    // jsdom 等環境沒有 createObjectURL；沒有就不預覽，不影響送出。
    if (!file || typeof URL.createObjectURL !== "function") {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL?.(next);
  }, [file]);
  return url;
}

function FilePreview({ file }: { file: File }) {
  const url = useObjectUrl(file);
  if (!url) return null;
  const video = isVideoFile(file) || file.type.startsWith("video/");
  const image = !video && (isImageFile(file) || file.type.startsWith("image/"));
  if (!video && !image) return null;
  return (
    <div
      data-testid="file-preview"
      className="flex aspect-[4/3] max-h-[50dvh] w-full items-center justify-center overflow-hidden rounded-md border border-border"
      style={checkerboardStyle}
    >
      {video ? (
        <video
          src={url}
          muted
          loop
          autoPlay
          playsInline
          aria-label={`預覽 ${file.name}`}
          className="h-full w-full object-contain"
        />
      ) : (
        <img src={url} alt={`預覽 ${file.name}`} className="h-full w-full object-contain" />
      )}
    </div>
  );
}

/** 同一欄位可收影片或圖片時，選好檔案後圖示跟著實際類型走。 */
function iconFor(file: File | null, fallback: string): string {
  if (!file) return fallback;
  if (isVideoFile(file) || file.type.startsWith("video/")) return "movie";
  if (isImageFile(file) || file.type.startsWith("image/")) return "image";
  return fallback;
}

export function FileDropField({
  label,
  inputLabel,
  kinds,
  file,
  onChange,
  hint,
  chooseText,
  icon,
  disabled = false,
  optional = false,
  variant = "compact",
}: FileDropFieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function accept(next: File | undefined): void {
    if (!next) return;
    const problem = checkFile(next, kinds);
    setError(problem);
    if (!problem) onChange(next);
  }

  function handleDragOver(event: DragEvent<HTMLLabelElement>): void {
    event.preventDefault();
    if (disabled) return;
    event.dataTransfer.dropEffect = "copy";
    setDragging(true);
  }

  function handleDragLeave(event: DragEvent<HTMLLabelElement>): void {
    // 拖過框內的子元素也會觸發 dragleave；只有真的離開外框才取消提示。
    const related = event.relatedTarget as Node | null;
    if (related && event.currentTarget.contains(related)) return;
    setDragging(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>): void {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    accept(event.dataTransfer.files?.[0]);
  }

  const zoneState = disabled
    ? "cursor-not-allowed opacity-60 border-border"
    : dragging
      ? "border-primary bg-primary-50 text-content"
      : error
        ? "border-danger hover:bg-surface-sunken"
        : file
          ? "border-border-strong border-solid hover:bg-surface-sunken"
          : "border-border-strong hover:border-primary hover:bg-surface-sunken";

  const zoneLayout = variant === "media"
    ? "flex-col items-stretch gap-3 p-3"
    : "flex-row items-center gap-3 px-3 py-2.5";

  const describedBy = [hintId, error ? errorId : ""].filter(Boolean).join(" ");

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex min-w-0 items-baseline justify-between gap-2">
        <span className={fieldLabelClassName}>
          {label}
          {optional && <span className="ml-1 font-normal text-content-subtle">（選填）</span>}
        </span>
        {file && !disabled && (
          <button
            type="button"
            onClick={() => {
              setError(null);
              onChange(null);
            }}
            aria-label={`移除 ${file.name}`}
            className="shrink-0 rounded text-xs text-content-muted underline-offset-2 hover:text-content hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            移除
          </button>
        )}
      </div>
      <label
        data-dragging={dragging || undefined}
        onDragEnter={handleDragOver}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={[
          "relative flex min-w-0 cursor-pointer rounded-md border border-dashed bg-surface transition-colors motion-reduce:transition-none active:bg-surface-sunken",
          "has-[:focus-visible]:border-primary has-[:focus-visible]:ring-[0.1875rem] has-[:focus-visible]:ring-primary/30",
          zoneLayout,
          zoneState,
        ].join(" ")}
      >
        <input
          type="file"
          accept={acceptList(kinds)}
          aria-label={inputLabel ?? label}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          disabled={disabled}
          className="sr-only"
          onChange={(e) => {
            accept(e.target.files?.[0]);
            // 存的是 File 本身；清掉輸入框，同一個檔案再選一次也會觸發。
            e.target.value = "";
          }}
        />
        {file && variant === "media" && <FilePreview file={file} />}
        <span
          className={
            !file && variant === "media"
              ? "flex min-w-0 flex-col items-center gap-2 py-8 text-center"
              : "flex min-w-0 items-center gap-3"
          }
        >
          <span
            aria-hidden="true"
            className="material-symbols-outlined inline-flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden text-[1.25rem] leading-none text-content-subtle"
          >
            {iconFor(file, icon)}
          </span>
          {file ? (
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="min-w-0 truncate text-sm text-content">{file.name}</span>
              <span className="text-xs text-content-subtle">
                {formatFileSize(file.size)} · 點這裡或拖放可換檔
              </span>
            </span>
          ) : (
            <span className="flex min-w-0 flex-1 flex-wrap items-baseline justify-center gap-x-1.5 text-sm text-content-muted">
              <span className="font-medium text-primary-600 dark:text-primary">{chooseText}</span>
              <span>或拖放到這裡</span>
            </span>
          )}
        </span>
      </label>
      <p id={hintId} className={fieldHintClassName}>
        {hint}
      </p>
      {error && (
        <p id={errorId} role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {error}
        </p>
      )}
    </div>
  );
}
