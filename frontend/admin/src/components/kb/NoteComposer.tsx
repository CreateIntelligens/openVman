import { useState } from "react";

import type { KnowledgeNoteFormat } from "../../api";
import QaDocEditor from "./QaDocEditor";

const FORMAT_OPTIONS: { value: KnowledgeNoteFormat; label: string; icon: string }[] = [
  { value: "text", label: "純文字", icon: "notes" },
  { value: "qa", label: "QA 問答", icon: "quiz" },
];

const QA_HINT = "以問答列輸入，建立後會直接成為問答樹節點（節點名稱＝標題）。";
const TEXT_HINT = "純文字筆記會存放在 knowledge/notes/。";

export default function NoteComposer({
  creating,
  onClose,
  onCreate,
}: {
  creating: boolean;
  onClose: () => void;
  onCreate: (title: string, content: string, format: KnowledgeNoteFormat) => void;
}) {
  const [format, setFormat] = useState<KnowledgeNoteFormat>("text");
  const [title, setTitle] = useState("");
  const [textContent, setTextContent] = useState("");
  const [qaContent, setQaContent] = useState("");

  const content = format === "qa" ? qaContent : textContent;
  const canCreate = !creating && title.trim().length > 0 && content.trim().length > 0;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 dark:border-slate-800/60 bg-white dark:bg-slate-950/30 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <button
            onClick={onClose}
            className="p-1 rounded-md text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="返回"
            aria-label="返回"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">arrow_back</span>
          </button>
          <span className="material-symbols-outlined text-primary text-[1.25rem]">edit_note</span>
          <span className="text-sm font-semibold text-slate-900 dark:text-white">新增手動來源</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-100 dark:bg-slate-900/40 p-0.5">
            {FORMAT_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setFormat(option.value)}
                className={`flex items-center gap-1 px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
                  format === option.value
                    ? "bg-white dark:bg-slate-800 text-primary shadow-sm"
                    : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                }`}
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[0.875rem]">{option.icon}</span>
                {option.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => onCreate(title, content, format)}
            disabled={!canCreate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            <span aria-hidden="true" className={`material-symbols-outlined text-[0.875rem] ${creating ? "animate-spin" : ""}`}>
              {creating ? "sync" : "save"}
            </span>
            {creating ? "建立中..." : "建立來源"}
          </button>
        </div>
      </div>

      <div className="px-4 pt-3 shrink-0 space-y-2">
        <div className="flex items-center gap-3">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 shrink-0">標題</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="例如：產品定位整理"
            className="flex-1 min-w-0 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950/60 px-4 py-2 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
          />
        </div>
        <p className="text-xs text-slate-400 dark:text-slate-500">
          {format === "qa" ? QA_HINT : TEXT_HINT}
        </p>
      </div>

      {format === "qa" ? (
        <QaDocEditor content={qaContent} onChange={setQaContent} />
      ) : (
        <div className="flex-1 flex flex-col min-h-0 px-4 pb-3 pt-2">
          <textarea
            value={textContent}
            onChange={(e) => setTextContent(e.target.value)}
            placeholder="貼上整理好的知識內容..."
            className="flex-1 w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950/60 px-4 py-3 text-sm text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none resize-none"
          />
          <p className="mt-2 text-xs text-slate-500 shrink-0">{textContent.length.toLocaleString()} chars</p>
        </div>
      )}
    </div>
  );
}
