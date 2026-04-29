import type { RefObject } from "react";
import { SOURCE_MODES, SOURCE_MODE_COPY, getSourceMeta, type SourceMode } from "./helpers";

export default function SourcePanel({
  activeMode,
  setActiveMode,
  uploading,
  uploadInputRef,
  currentDir,
  crawlUrlValue,
  setCrawlUrlValue,
  crawling,
  onCrawl,
  onShowNote,
}: {
  activeMode: SourceMode;
  setActiveMode: (m: SourceMode) => void;
  uploading: boolean;
  uploadInputRef: RefObject<HTMLInputElement | null>;
  currentDir: string;
  crawlUrlValue: string;
  setCrawlUrlValue: (v: string) => void;
  crawling: boolean;
  onCrawl: () => void;
  onShowNote: () => void;
}) {
  return (
    <div className="border-b border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-950/30 px-4 py-3 space-y-3 shrink-0">
      <div className="flex gap-2">
        {SOURCE_MODES.map((mode) => {
          const meta = getSourceMeta(mode);
          return (
            <button
              key={mode}
              onClick={() => setActiveMode(mode)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                activeMode === mode
                  ? "bg-primary/15 text-primary border border-primary/30"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800/50 border border-transparent"
              }`}
            >
              <span className="material-symbols-outlined text-[1rem]">{meta.icon}</span>
              {meta.label}
            </button>
          );
        })}
        <span className="ml-2 text-xs text-slate-500 self-center">{SOURCE_MODE_COPY[activeMode]}</span>
      </div>

      {activeMode === "upload" && (
        <button
          type="button"
          onClick={() => uploadInputRef.current?.click()}
          disabled={uploading}
          className="w-full rounded-lg border border-dashed border-slate-200 dark:border-slate-700 hover:border-primary/50 bg-slate-50 dark:bg-slate-900/20 hover:bg-primary/5 transition-all py-4 flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 text-sm text-slate-500 dark:text-slate-400"
        >
          <span className="material-symbols-outlined text-[1.25rem]">cloud_upload</span>
          {uploading ? "上傳中..." : `選擇檔案上傳到 ${currentDir}`}
        </button>
      )}

      {activeMode === "web" && (
        <div className="flex gap-2">
          <input
            type="url"
            className="flex-1 bg-white dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-lg px-4 py-2 text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:ring-2 focus:ring-primary focus:border-transparent focus:outline-none"
            placeholder="https://example.com/article"
            value={crawlUrlValue}
            onChange={(e) => setCrawlUrlValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onCrawl()}
            disabled={crawling}
          />
          <button
            onClick={onCrawl}
            disabled={crawling || !crawlUrlValue.trim()}
            className="bg-primary text-white px-4 py-2 rounded-lg font-bold text-sm flex items-center gap-1.5 hover:bg-primary/90 transition-all disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[1rem]">{crawling ? "hourglass_top" : "download"}</span>
            {crawling ? "擷取中..." : "匯入"}
          </button>
        </div>
      )}

      {activeMode === "manual" && (
        <button
          type="button"
          onClick={onShowNote}
          className="flex items-center gap-2 rounded-lg bg-primary/10 border border-primary/30 px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/15 transition-colors"
        >
          <span className="material-symbols-outlined text-[1.125rem]">note_add</span>
          新增筆記
        </button>
      )}
    </div>
  );
}
