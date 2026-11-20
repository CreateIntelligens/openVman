import { useId, useRef, type ChangeEvent, type RefObject } from "react";

import type { KnowledgeNoteFormat } from "../../api";
import {
  IMPORT_ACCEPT,
  IMPORT_FORMATS_LABEL,
  type ImportTargetOption,
} from "../../hooks/useKnowledgeImport";
import Select from "../Select";

interface SourcePanelProps {
  vendor?: boolean;
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
  /** 這個帳號能不能用「AI 整理排版」；不能的話只有直接放進知識庫一種做法，不給選。 */
  allowAiCleanup?: boolean;
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
  vendor = false,
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
  allowAiCleanup = true,
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
        {allowAiCleanup ? (
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium text-content">這批文件要怎麼放進去</legend>
            <label className="flex cursor-pointer items-start gap-2 text-sm text-content">
              <input
                type="radio"
                name={normalizeName}
                className="mt-1 h-4 w-4 shrink-0 accent-primary"
                checked={skipNormalize}
                onChange={() => onSkipNormalizeChange(true)}
              />
              直接放進知識庫（內容照原樣，AI 回答時會查這份資料）
            </label>
            <label className="flex cursor-pointer items-start gap-2 text-sm text-content">
              <input
                type="radio"
                name={normalizeName}
                className="mt-1 h-4 w-4 shrink-0 accent-primary"
                checked={!skipNormalize}
                onChange={() => onSkipNormalizeChange(false)}
              />
              先讓 AI 整理排版再放進去（適合換行或排版很亂的文件）
            </label>
            <p className="text-xs text-content-muted">
              每次上傳開始後，會回到「直接放進知識庫」。問答表不看這個設定。
            </p>
          </fieldset>
        ) : (
          <p className="text-sm text-content">
            這批文件會直接放進知識庫（內容照原樣，AI 回答時會查這份資料）。
          </p>
        )}

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

        {vendor ? (
          <div className="space-y-2 text-sm text-content-muted">
            <p>
              <strong className="text-content">問答表</strong>　有「問題」和「答案」兩欄的試算表會放進快速回覆。
              可加「第一層」「第二層」兩欄指定分類，會放在該題語言的分類底下。系統會辨識每題語言，沒有對應的語言分類時先放在最上層。
              同名問答表重傳時只會加新題目。只要有題目和既有的同名但答案不同，整份都不會匯入，畫面會列出是哪幾題，改好再傳一次。
            </p>
            <p>
              <strong className="text-content">一般文件</strong>　可上傳 Word（.docx）、PDF、文字檔（.md、.txt）或試算表（.xlsx、.csv）。
              每個檔案限 {maxUploadLabel}。
            </p>
          </div>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm text-content-muted">
            <li>有「問題」「答案」欄位的 Excel 或 CSV，會放進快速問答。</li>
            <li>同名的問答表再傳一次是加上新題目，原本的題目都留著。只要有一題的答案和現有的不同，整份都不會匯入，畫面會列出是哪幾題。</li>
            <li>想指定放在哪個分類，可加「第一層」「第二層」兩欄，會放在該題語言的分類底下。沒填就放在以檔名命名的分類。</li>
            <li>中文、英文、西文混在同一張表也可以。系統會辨識每題語言，沒有對應的語言分類時先放在最上層。</li>
            <li>一般文件會保留原文供 AI 回答時查閱。選 AI 整理時會以原本的語言整理。</li>
            <li>可以上傳 {IMPORT_FORMATS_LABEL}，每個檔案 {maxUploadLabel} 以內。</li>
          </ul>
        )}

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
                  {vendor && template.file.endsWith(".md") ? "整理好的文件（文字檔）" : template.label}
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
            問答表一律放進{vendor ? "快速回覆" : "快速問答"}。
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
