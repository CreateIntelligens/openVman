import { useId, useRef, type ChangeEvent, type RefObject } from "react";

import type { KnowledgeNoteFormat } from "../../api";
import {
  IMPORT_ACCEPT,
  IMPORT_FORMATS_LABEL,
  type ImportTargetOption,
} from "../../hooks/useKnowledgeImport";
import Select from "../Select";

interface SourcePanelProps {
  onPickFiles: (files: File[]) => void;
  /** 例如「100 MB」。 */
  maxUploadLabel: string;
  targetDir: string;
  targetOptions: ImportTargetOption[];
  onTargetDirChange: (dir: string) => void;
  skipNormalize: boolean;
  onSkipNormalizeChange: (skip: boolean) => void;
  /** 外面要能打開同一個選檔視窗，例如匯入結果的「重新選檔案」。 */
  fileInputRef?: RefObject<HTMLInputElement>;
  crawlUrlValue: string;
  setCrawlUrlValue: (value: string) => void;
  crawling: boolean;
  onCrawl: () => void;
  onOpenComposer: (format: KnowledgeNoteFormat) => void;
  /** 知識庫還是空的：上傳區是畫面的主角。 */
  prominent?: boolean;
}

/** 新增資料的所有入口。規則直接寫在畫面上，不靠滑過才出現的說明。 */
// 與 vite.config 的 base 一致；public/ 底下的檔案跟打包後的資源走同一個前綴。
const TEMPLATE_BASE = "/admin/templates/";

// 範例檔放在 public/templates，內容是虛構的服務中心，不含任何客戶資料。
export const IMPORT_TEMPLATES = [
  { file: "範例_常見問題.xlsx", label: "問答表（Excel）" },
  { file: "範例_常見問題.csv", label: "問答表（CSV）" },
  { file: "範例_整理好的文件.md", label: "整理好的文件（Markdown）" },
] as const;

export default function SourcePanel({
  onPickFiles,
  maxUploadLabel,
  targetDir,
  targetOptions,
  onTargetDirChange,
  skipNormalize,
  onSkipNormalizeChange,
  fileInputRef,
  crawlUrlValue,
  setCrawlUrlValue,
  crawling,
  onCrawl,
  onOpenComposer,
  prominent = false,
}: SourcePanelProps) {
  const ownInputRef = useRef<HTMLInputElement>(null);
  const inputRef = fileInputRef ?? ownInputRef;
  const urlInputId = useId();
  const normalizeName = useId();

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    onPickFiles(Array.from(event.target.files ?? []));
    // 清空才選得了同一個檔案：改好之後重傳同名檔是常見操作。
    event.target.value = "";
  };

  return (
    <div className="space-y-6">
      <section aria-label="上傳檔案" className="space-y-4">
        {/* 選了檔案就開始上傳，所以要放在拖放區上面：由上往下操作的人先選好再放檔案。 */}
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium text-content">這批文件要怎麼放進去</legend>
          <label className="flex cursor-pointer items-start gap-2 text-sm text-content">
            <input
              type="radio"
              name={normalizeName}
              className="mt-1 h-4 w-4 shrink-0 accent-primary"
              checked={!skipNormalize}
              onChange={() => onSkipNormalizeChange(false)}
            />
            讓 AI 整理排版（適合亂亂的筆記）
          </label>
          <label className="flex cursor-pointer items-start gap-2 text-sm text-content">
            <input
              type="radio"
              name={normalizeName}
              className="mt-1 h-4 w-4 shrink-0 accent-primary"
              checked={skipNormalize}
              onChange={() => onSkipNormalizeChange(true)}
            />
            照原樣放進去，不讓 AI 改（適合已經整理好的文件）
          </label>
          <p className="text-xs text-content-muted">
            每次上傳開始後，會回到「讓 AI 整理排版」。問答表不看這個設定。
          </p>
        </fieldset>

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className={`flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border-strong bg-surface-raised px-4 text-center transition-colors hover:border-primary hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
            prominent ? "py-16" : "py-8"
          }`}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[2rem] text-primary">
            upload_file
          </span>
          <span className="text-base font-semibold text-content">
            把檔案拖到這裡，或點這裡選擇檔案
          </span>
        </button>
        <input
          ref={inputRef}
          type="file"
          data-testid="knowledge-upload-input"
          className="hidden"
          accept={IMPORT_ACCEPT}
          multiple
          tabIndex={-1}
          aria-hidden="true"
          onChange={handleInputChange}
        />

        <ul className="list-disc space-y-1 pl-5 text-sm text-content-muted">
          <li>有「問題」「答案」欄位的 Excel 或 CSV，會放進快速問答。</li>
          <li>同名的問答表再傳一次是加上新題目，原本的題目都留著。答案和現有的不同時不會匯入，畫面會列出是哪幾題。</li>
          <li>想指定放在哪個分類，加一欄「分類」，用斜線分層，例如「中文/產品/EUS」。沒填就放在以檔名命名的分類。</li>
          <li>其他文件照上面的選擇加入知識庫。AI 整理時內容維持原本的語言，不會翻譯。</li>
          <li>可以上傳 {IMPORT_FORMATS_LABEL}，每個檔案 {maxUploadLabel} 以內。</li>
        </ul>

        <div className="space-y-1 text-sm">
          <p className="font-medium text-content">不知道怎麼排？下載範例照著填：</p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            {IMPORT_TEMPLATES.map((template) => (
              <li key={template.file}>
                <a
                  className="text-primary underline underline-offset-2 hover:text-primary-600"
                  href={`${TEMPLATE_BASE}${encodeURIComponent(template.file)}`}
                  download={template.file}
                >
                  {template.label}
                </a>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-1">
          <p className="text-sm font-medium text-content">放到哪個資料夾</p>
          <Select
            className="sm:max-w-[24rem]"
            ariaLabel="放到哪個資料夾"
            value={targetDir}
            options={targetOptions}
            onChange={onTargetDirChange}
          />
          <p className="text-xs text-content-muted">
            問答表不看這個設定，一律放進快速問答。
          </p>
        </div>
      </section>

      <section aria-labelledby={`${urlInputId}-heading`} className="space-y-3">
        <h3 id={`${urlInputId}-heading`} className="text-sm font-semibold text-content">其他方式</h3>
        <div className="space-y-1">
          <label htmlFor={urlInputId} className="block text-sm text-content-muted">
            貼網址，把網頁內容加入知識庫
          </label>
          <div className="flex gap-2">
            <input
              id={urlInputId}
              type="url"
              inputMode="url"
              className="input min-w-0 flex-1"
              placeholder="https://example.com/article"
              value={crawlUrlValue}
              onChange={(event) => setCrawlUrlValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !crawling) onCrawl();
              }}
              disabled={crawling}
            />
            <button
              type="button"
              onClick={onCrawl}
              disabled={crawling || !crawlUrlValue.trim()}
              className="btn btn-ghost shrink-0"
            >
              {crawling ? "匯入中…" : "匯入"}
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => onOpenComposer("text")}>
            自己輸入一篇文件
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => onOpenComposer("qa")}>
            自己輸入問答
          </button>
        </div>
      </section>
    </div>
  );
}
