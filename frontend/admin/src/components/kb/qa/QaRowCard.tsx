import { useState, type DragEvent, type ReactNode } from "react";

import QaImagePreview from "../QaImagePreview";
import AutoTextarea from "./AutoTextarea";

export type QaRowField = "question" | "answer" | "img" | "url" | "hidden";

interface QaRowCardProps {
  index: number;
  question: string;
  answer: string;
  img: string;
  url: string;
  hidden: boolean;
  /** 同一列表來自多份檔案時才給，只有一份時放列表上方就好。 */
  sourceFile?: string;
  onChange: (field: QaRowField, value: string | boolean) => void;
  onRemove: () => void;
  /** 圖片欄旁的動作（上傳），打開圖片欄才出現。 */
  imageAction?: ReactNode;
  rowProps: {
    "data-reorder-row": boolean;
    onDragOver: (event: DragEvent<HTMLElement>) => void;
    onDrop: (event: DragEvent<HTMLElement>) => void;
  };
  handleProps: {
    draggable: boolean;
    onDragStart: (event: DragEvent<HTMLElement>) => void;
    onDragEnd: () => void;
  };
  dropLine: "before" | "after" | null;
  dragging: boolean;
}

const FIELD_CLASS =
  "w-full rounded-lg border border-transparent bg-transparent px-2.5 py-1.5 text-sm leading-relaxed text-content placeholder:text-content-subtle hover:border-border focus:border-primary/50 focus:bg-surface focus:outline-none focus:ring-1 focus:ring-primary/50 dark:focus:bg-surface/70";
const EXTRA_INPUT_CLASS =
  "min-w-0 flex-1 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs text-content-muted focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/50";
const ICON_BUTTON_CLASS =
  "inline-flex h-8 w-7 items-center justify-center rounded-lg text-content-subtle transition-colors hover:bg-surface-sunken hover:text-content";

export default function QaRowCard({
  index,
  question,
  answer,
  img,
  url,
  hidden,
  sourceFile,
  onChange,
  onRemove,
  imageAction,
  rowProps,
  handleProps,
  dropLine,
  dragging,
}: QaRowCardProps) {
  const [imageOpen, setImageOpen] = useState(false);
  const [urlOpen, setUrlOpen] = useState(false);
  const showImage = Boolean(img) || imageOpen;
  const showUrl = Boolean(url) || urlOpen;

  return (
    <article
      {...rowProps}
      className={`group relative flex flex-wrap items-start gap-1 px-2 py-2 transition-colors hover:bg-surface-sunken/40 lg:flex-nowrap ${
        dragging ? "opacity-40" : ""
      }`}
    >
      {dropLine && (
        <span
          aria-hidden="true"
          className={`pointer-events-none absolute inset-x-0 z-10 h-0.5 bg-primary ${
            dropLine === "before" ? "top-0" : "bottom-0"
          }`}
        />
      )}

      <button
        type="button"
        {...handleProps}
        aria-label={`拖曳調整問答 ${index + 1} 的順序`}
        title="拖曳調整順序"
        className="mt-1 flex h-7 w-5 shrink-0 cursor-grab items-center justify-center rounded text-content-subtle hover:text-content active:cursor-grabbing"
      >
        <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">drag_indicator</span>
      </button>
      <span className="mt-2 w-6 shrink-0 text-right font-mono text-xs tabular-nums text-content-subtle">
        {index + 1}
      </span>

      {/* 窄版文字佔滿整行，把手和操作排在上面，不跟內容搶寬度。 */}
      <div className={`order-last w-full min-w-0 lg:order-none lg:w-auto lg:flex-1 ${hidden ? "opacity-60" : ""}`}>
        <div className="grid gap-0.5 lg:grid-cols-[2fr_3fr] lg:gap-2">
          <AutoTextarea
            aria-label={`問答 ${index + 1} 的問題`}
            value={question}
            onChange={(e) => onChange("question", e.target.value)}
            placeholder="請輸入問題"
            className={`${FIELD_CLASS} max-h-[30dvh] font-medium`}
          />
          <AutoTextarea
            aria-label={`問答 ${index + 1} 的答案`}
            value={answer}
            onChange={(e) => onChange("answer", e.target.value)}
            placeholder="請輸入答案"
            className={`${FIELD_CLASS} max-h-[40dvh]`}
          />
        </div>

        {(showImage || showUrl || sourceFile) && (
          <div className="flex flex-wrap items-center gap-2 px-2.5 pb-0.5 pt-1">
            {showImage && (
              <div className="flex min-w-[min(100%,16rem)] flex-1 items-center gap-2">
                <QaImagePreview compact imageId={img} alt={`${question || `問答 ${index + 1}`}的參考圖片`} />
                <input
                  type="text"
                  aria-label={`問答 ${index + 1} 的圖片 ID`}
                  value={img}
                  onChange={(e) => onChange("img", e.target.value)}
                  placeholder="圖片 ID"
                  className={`${EXTRA_INPUT_CLASS} font-mono`}
                />
                {imageAction}
              </div>
            )}
            {showUrl && (
              <input
                type="text"
                aria-label={`問答 ${index + 1} 的外部連結`}
                value={url}
                onChange={(e) => onChange("url", e.target.value)}
                placeholder="外部連結"
                className={`${EXTRA_INPUT_CLASS} min-w-[min(100%,16rem)]`}
              />
            )}
            {sourceFile && (
              <span className="ml-auto truncate text-xs text-content-subtle" title={sourceFile}>
                {sourceFile.split("/").pop()}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="ml-auto mt-0.5 flex shrink-0 items-center">
        {!showImage && (
          <button type="button" className={ICON_BUTTON_CLASS} onClick={() => setImageOpen(true)} aria-label="圖片" title="加上圖片">
            <span aria-hidden="true" className="material-symbols-outlined text-base">image</span>
          </button>
        )}
        {!showUrl && (
          <button type="button" className={ICON_BUTTON_CLASS} onClick={() => setUrlOpen(true)} aria-label="連結" title="加上外部連結">
            <span aria-hidden="true" className="material-symbols-outlined text-base">link</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => onChange("hidden", !hidden)}
          className={`inline-flex h-8 min-w-7 items-center justify-center gap-1 rounded-lg px-1.5 text-xs font-medium transition-colors ${
            hidden
              ? "bg-surface-sunken text-content-muted hover:text-content"
              : "text-content-subtle hover:bg-surface-sunken hover:text-content"
          }`}
          aria-label={hidden ? "目前已隱藏，點擊以顯示" : "目前顯示中，點擊以隱藏"}
          title={hidden ? "目前已隱藏，點擊以顯示" : "目前顯示中，點擊以隱藏"}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-base">
            {hidden ? "visibility_off" : "visibility"}
          </span>
          {hidden && "已隱藏"}
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="inline-flex h-8 w-7 items-center justify-center rounded-lg text-content-subtle transition-colors hover:bg-danger/10 hover:text-danger"
          aria-label={`刪除問答 ${index + 1}`}
          title="刪除此行"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-base">delete</span>
        </button>
      </div>
    </article>
  );
}

/** 問題／答案的欄名：每列重複標會很吵，寬版只在列表頂端標一次。 */
export function QaRowListHeader() {
  return (
    <div className="sticky top-0 z-20 hidden items-center gap-1 border-b border-border bg-surface-raised px-2 py-1.5 text-xs font-semibold text-content-subtle lg:flex">
      <span className="w-5 shrink-0" />
      <span className="w-6 shrink-0" />
      <div className="grid min-w-0 flex-1 grid-cols-[2fr_3fr] gap-2 px-2.5">
        <span>問題</span>
        <span>答案</span>
      </div>
      <span className="w-[5.25rem] shrink-0" />
    </div>
  );
}
