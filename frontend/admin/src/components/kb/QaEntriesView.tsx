import { useState } from "react";
import { parseQaMarkdown } from "./qaMarkdown";

export default function QaEntriesView({ content }: { content: string }) {
  const entries = parseQaMarkdown(content);
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  if (entries.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-slate-500">
        尚無可解析的問答內容
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-2">
      {entries.map((entry, index) => {
        const isOpen = openIndex === index;
        return (
          <div
            key={`${entry.question}-${index}`}
            className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950/40 overflow-hidden"
          >
            <button
              type="button"
              onClick={() => setOpenIndex(isOpen ? null : index)}
              className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm font-semibold text-slate-900 hover:bg-slate-50 dark:text-white dark:hover:bg-slate-900/60"
            >
              <span className="flex items-center gap-2 min-w-0">
                <span className="material-symbols-outlined shrink-0 text-[1.125rem] text-primary">quiz</span>
                <span className="truncate">{entry.question}</span>
              </span>
              <span className="material-symbols-outlined shrink-0 text-[1.125rem] text-slate-400">
                {isOpen ? "expand_less" : "expand_more"}
              </span>
            </button>
            {isOpen && (
              <div className="border-t border-slate-200 px-4 py-3 text-sm leading-relaxed text-slate-600 dark:border-slate-800 dark:text-slate-300 whitespace-pre-wrap">
                {entry.answer || "（無答案內容）"}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
