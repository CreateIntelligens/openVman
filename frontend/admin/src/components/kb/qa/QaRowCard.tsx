import { useId, useState, type DragEvent } from "react";

import QaImagePreview from "../QaImagePreview";
import AutoTextarea from "./AutoTextarea";

export type QaRowField = "question" | "answer" | "img" | "url" | "hidden";

export const QA_HIDDEN_HINT = "「已隱藏」的問題不會出現在訪客的選單，但 AI 回答時還是會用。";

interface QaRowCardProps {
  /** 在完整清單裡的位置，題號由它來：搜尋時清單變短，題號也不能跟著變。 */
  index: number;
  question: string;
  answer: string;
  img: string;
  url: string;
  hidden: boolean;
  /** 同一個清單來自多份檔案時才給，只有一份時放清單上方就好。 */
  sourceLabel?: string;
  /** 選單專用題目：沒有答案、圖片與連結，訪客點了照一般方式問。 */
  menuOnly?: boolean;
  /** 這一題也放在哪些分類；改答案時那些分類會一起變。 */
  alsoIn?: string[];
  /** 有給才出現「也放到其他分類」。 */
  onMount?: () => void;
  onChange: (field: QaRowField, value: string | boolean) => void;
  onRemove: () => void;
  /** 有給才出現「上傳圖片」。 */
  onPickImage?: () => void;
  uploadingImage?: boolean;
  /** 別的列正在上傳時不能再選檔案。 */
  uploadDisabled?: boolean;
  rowRef?: (element: HTMLElement | null) => void;
  highlighted?: boolean;
  invalidFields?: { question?: boolean; answer?: boolean };
  /** 不用拖曳的排序方式，手機也能用。沒給就不顯示；搜尋時顯示的不是完整順序，只留「移到第幾題」。 */
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  onMoveTo?: () => void;
  isFirst?: boolean;
  isLast?: boolean;
  /** 排序用。沒給就沒有把手：搜尋時顯示的不是完整順序，不能拖。 */
  rowProps?: {
    "data-reorder-row": boolean;
    onDragOver: (event: DragEvent<HTMLElement>) => void;
    onDrop: (event: DragEvent<HTMLElement>) => void;
  };
  handleProps?: {
    draggable: boolean;
    onDragStart: (event: DragEvent<HTMLElement>) => void;
    onDragEnd: () => void;
  };
  dropLine?: "before" | "after" | null;
  dragging?: boolean;
}

const ROW_BUTTON_CLASS = "btn btn-ghost gap-1 px-2 py-1 text-xs";
const FIELD_LABEL_CLASS = "block text-xs font-medium text-content-muted";

function fieldClass(invalid: boolean | undefined): string {
  return `input ${invalid ? "border-danger" : ""}`;
}

export default function QaRowCard({
  index,
  question,
  answer,
  img,
  url,
  hidden,
  sourceLabel,
  menuOnly = false,
  alsoIn = [],
  onMount,
  onMoveUp,
  onMoveDown,
  onMoveTo,
  isFirst = false,
  isLast = false,
  onChange,
  onRemove,
  onPickImage,
  uploadingImage = false,
  uploadDisabled = false,
  rowRef,
  highlighted = false,
  invalidFields,
  rowProps,
  handleProps,
  dropLine = null,
  dragging = false,
}: QaRowCardProps) {
  const number = index + 1;
  const fieldId = useId();
  // 欄位一旦打開就留著：不然把舊編號刪光準備重打時，輸入框會當場消失。
  const [imageOpen, setImageOpen] = useState(Boolean(img));
  const [urlOpen, setUrlOpen] = useState(Boolean(url));
  const showImage = imageOpen || Boolean(img);
  const showUrl = urlOpen || Boolean(url);

  const removeImage = () => {
    onChange("img", "");
    setImageOpen(false);
  };

  const removeUrl = () => {
    onChange("url", "");
    setUrlOpen(false);
  };

  return (
    <article
      {...rowProps}
      ref={rowRef}
      tabIndex={-1}
      aria-label={`第 ${number} 題`}
      data-highlighted={highlighted || undefined}
      className={`relative scroll-mt-28 px-3 py-2.5 transition-colors lg:scroll-mt-12 ${
        highlighted ? "bg-primary/10 ring-1 ring-inset ring-primary" : ""
      } ${dragging ? "opacity-40" : ""}`}
    >
      {dropLine && (
        <span
          aria-hidden="true"
          className={`pointer-events-none absolute inset-x-0 z-10 h-0.5 bg-primary ${
            dropLine === "before" ? "top-0" : "bottom-0"
          }`}
        />
      )}

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {handleProps && (
          <button
            type="button"
            {...handleProps}
            aria-label={`拖曳調整第 ${number} 題的順序`}
            className="flex h-7 w-5 shrink-0 cursor-grab items-center justify-center rounded text-content-subtle hover:text-content active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-50 [@media(pointer:coarse)]:hidden"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">drag_indicator</span>
          </button>
        )}
        <span className="shrink-0 text-sm font-semibold text-content">第 {number} 題</span>
        {sourceLabel && (
          <span className="min-w-0 truncate text-xs text-content-subtle" title={sourceLabel}>
            來自：{sourceLabel}
          </span>
        )}
        {menuOnly && (
          <span className="rounded border border-border px-1.5 py-0.5 text-xs text-content-muted">
            只在選單
          </span>
        )}

        <div className="flex flex-wrap items-center gap-1">
          {onMoveUp && (
            <button
              type="button"
              className={ROW_BUTTON_CLASS}
              onClick={onMoveUp}
              disabled={isFirst}
              aria-label={`第 ${number} 題上移`}
            >
              上移
            </button>
          )}
          {onMoveDown && (
            <button
              type="button"
              className={ROW_BUTTON_CLASS}
              onClick={onMoveDown}
              disabled={isLast}
              aria-label={`第 ${number} 題下移`}
            >
              下移
            </button>
          )}
          {onMoveTo && (
            <button
              type="button"
              className={ROW_BUTTON_CLASS}
              onClick={onMoveTo}
              aria-label={`把第 ${number} 題移到第幾題`}
            >
              移到第幾題
            </button>
          )}
        </div>

        <div className="ml-auto flex flex-wrap items-center justify-end gap-1">
          {onMount && (
            <button
              type="button"
              className={ROW_BUTTON_CLASS}
              onClick={onMount}
              aria-label={`把第 ${number} 題也放到其他分類`}
            >
              也放到其他分類
            </button>
          )}
          {!menuOnly && !showImage && (
            <button
              type="button"
              className={ROW_BUTTON_CLASS}
              onClick={() => setImageOpen(true)}
              aria-label={`第 ${number} 題加圖片`}
            >
              加圖片
            </button>
          )}
          {!menuOnly && !showUrl && (
            <button
              type="button"
              className={ROW_BUTTON_CLASS}
              onClick={() => setUrlOpen(true)}
              aria-label={`第 ${number} 題加連結`}
            >
              加連結
            </button>
          )}
          <button
            type="button"
            onClick={() => onChange("hidden", !hidden)}
            className={`${ROW_BUTTON_CLASS} ${hidden ? "bg-surface-sunken" : ""}`}
            aria-label={hidden
              ? `第 ${number} 題已隱藏，按一下改成顯示`
              : `第 ${number} 題顯示中，按一下隱藏`}
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">
              {hidden ? "visibility_off" : "visibility"}
            </span>
            {/* 寫成按了會發生什麼；只寫「顯示中」看起來像狀態，不像按鈕。 */}
            {hidden ? "已隱藏 · 改回顯示" : "隱藏這題"}
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="btn btn-danger gap-1 px-2 py-1 text-xs"
            aria-label={alsoIn.length > 0 ? `把第 ${number} 題從這個分類拿掉` : `刪除第 ${number} 題`}
          >
            {/* 也放在別的分類時只是從這裡拿掉，題目和答案還在。 */}
            {alsoIn.length > 0 ? "從這裡拿掉" : "刪除"}
          </button>
        </div>
      </div>
      {alsoIn.length > 0 && (
        <p className="mt-1 text-xs text-content-muted">
          這題也放在：{alsoIn.join("、")}。改答案時那裡會一起改。
        </p>
      )}

      <div className={`mt-1.5 grid gap-2 ${menuOnly ? "" : "lg:grid-cols-[2fr_3fr]"} ${hidden ? "opacity-60" : ""}`}>
        {/* 寬版的欄名在清單頂端標一次就好，每列重複會很吵。 */}
        <div className="min-w-0">
          <span aria-hidden="true" className={`${FIELD_LABEL_CLASS} mb-0.5 lg:hidden`}>問題</span>
          <AutoTextarea
            data-qa-field="question"
            aria-label={`第 ${number} 題的問題`}
            aria-invalid={invalidFields?.question || undefined}
            value={question}
            onChange={(e) => onChange("question", e.target.value)}
            placeholder="請輸入問題"
            className={`${fieldClass(invalidFields?.question)} max-h-[30dvh] font-medium placeholder:text-content-subtle`}
          />
        </div>
        {menuOnly ? (
          <p className="text-xs text-content-muted">
            這題只放在選單，沒有固定答案。訪客點了以後，AI 會照一般問題回答。
          </p>
        ) : (
        <div className="min-w-0">
          <span aria-hidden="true" className={`${FIELD_LABEL_CLASS} mb-0.5 lg:hidden`}>答案</span>
          <AutoTextarea
            data-qa-field="answer"
            aria-label={`第 ${number} 題的答案`}
            aria-invalid={invalidFields?.answer || undefined}
            value={answer}
            onChange={(e) => onChange("answer", e.target.value)}
            placeholder="請輸入答案"
            className={`${fieldClass(invalidFields?.answer)} max-h-[40dvh] placeholder:text-content-subtle`}
          />
        </div>
        )}
      </div>

      {(showImage || showUrl) && (
        <div className={`mt-2 grid gap-2 lg:grid-cols-2 ${hidden ? "opacity-60" : ""}`}>
          {showImage && (
            <div className="min-w-0">
              <label htmlFor={`${fieldId}-img`} className={FIELD_LABEL_CLASS}>
                圖片編號（AI 用這題回答時會附上這張圖）
              </label>
              <div className="mt-0.5 flex flex-wrap items-center gap-2">
                <QaImagePreview compact imageId={img} alt={`${question || `第 ${number} 題`}的參考圖片`} />
                <input
                  id={`${fieldId}-img`}
                  type="text"
                  aria-label={`第 ${number} 題的圖片編號`}
                  value={img}
                  onChange={(e) => onChange("img", e.target.value)}
                  placeholder="圖片編號"
                  className="input min-w-0 flex-1 basis-32 font-mono text-xs placeholder:text-content-subtle"
                />
                {onPickImage && (
                  <button
                    type="button"
                    onClick={onPickImage}
                    disabled={uploadDisabled}
                    className={ROW_BUTTON_CLASS}
                    aria-label={`第 ${number} 題上傳圖片`}
                  >
                    {uploadingImage ? "上傳中…" : "上傳圖片"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={removeImage}
                  className={ROW_BUTTON_CLASS}
                  aria-label={`第 ${number} 題移除圖片`}
                >
                  移除
                </button>
              </div>
            </div>
          )}
          {showUrl && (
            <div className="min-w-0">
              <label htmlFor={`${fieldId}-url`} className={FIELD_LABEL_CLASS}>
                相關連結網址（AI 用這題回答時會附上「開啟相關連結」）
              </label>
              <div className="mt-0.5 flex flex-wrap items-center gap-2">
                <input
                  id={`${fieldId}-url`}
                  type="url"
                  aria-label={`第 ${number} 題的相關連結網址`}
                  value={url}
                  onChange={(e) => onChange("url", e.target.value)}
                  placeholder="https://"
                  className="input min-w-0 flex-1 basis-32 text-xs placeholder:text-content-subtle"
                />
                <button
                  type="button"
                  onClick={removeUrl}
                  className={ROW_BUTTON_CLASS}
                  aria-label={`第 ${number} 題移除連結`}
                >
                  移除
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

/** 問題和答案的欄名：寬版兩欄並排時才需要，窄版每個欄位自己有標。 */
export function QaRowListHeader() {
  return (
    <div className="sticky top-0 z-20 hidden gap-2 border-b border-border bg-surface-raised px-3 py-1.5 text-xs font-semibold text-content-muted lg:grid lg:grid-cols-[2fr_3fr]">
      <span>問題</span>
      <span>答案</span>
    </div>
  );
}
