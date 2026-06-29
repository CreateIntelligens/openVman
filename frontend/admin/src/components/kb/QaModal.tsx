import { useState } from "react";

import {
  createEmptyQaRow,
  hasIncompleteQaRows,
  hasUsableQaRow,
  qaRowsToMarkdown,
  type QaRow,
} from "./qaMarkdown";

export default function QaModal({
  qaTitle,
  setQaTitle,
  qaTargetDir,
  setQaTargetDir,
  directoryOptions,
  qaRows,
  setQaRows,
  creating,
  onClose,
  onCreate,
}: {
  qaTitle: string;
  setQaTitle: (value: string) => void;
  qaTargetDir: string;
  setQaTargetDir: (value: string) => void;
  directoryOptions: string[];
  qaRows: QaRow[];
  setQaRows: (rows: QaRow[]) => void;
  creating: boolean;
  onClose: () => void;
  onCreate: () => void;
}) {
  const [usingNewDirectory, setUsingNewDirectory] = useState(
    () => Boolean(qaTargetDir && !directoryOptions.includes(qaTargetDir)),
  );
  const markdownPreview = qaRowsToMarkdown(qaRows);
  const hasIncompleteRows = hasIncompleteQaRows(qaRows);
  const hasUsableRow = hasUsableQaRow(qaRows);
  const hasInvalidTargetDir = isInvalidTargetDir(qaTargetDir);
  const createDisabled = creating ||
    !qaTitle.trim() ||
    !hasUsableRow ||
    hasIncompleteRows ||
    hasInvalidTargetDir;

  const updateRow = (index: number, patch: Partial<QaRow>) => {
    setQaRows(qaRows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const deleteRow = (index: number) => {
    const next = qaRows.filter((_, i) => i !== index);
    setQaRows(next.length ? next : [createEmptyQaRow()]);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="mx-4 flex max-h-[92dvh] w-full max-w-5xl flex-col rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[1.25rem] text-primary">quiz</span>
            <span className="text-sm font-semibold text-slate-900 dark:text-white">新增 QA 來源</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
          >
            <span className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,38%)]">
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  標題
                </label>
                <input
                  value={qaTitle}
                  onChange={(event) => setQaTitle(event.target.value)}
                  placeholder="QA-2026-06-29-1430"
                  className="w-full rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-950/60 dark:text-white dark:placeholder:text-slate-500"
                />
              </div>

              <div className="space-y-2">
                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  目錄
                </label>
                <select
                  value={usingNewDirectory ? "__new__" : qaTargetDir}
                  onChange={(event) => {
                    if (event.target.value === "__new__") {
                      setUsingNewDirectory(true);
                      setQaTargetDir("");
                      return;
                    }
                    setUsingNewDirectory(false);
                    setQaTargetDir(event.target.value);
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-950/60 dark:text-white"
                >
                  <option value="">預設 notes</option>
                  {directoryOptions.map((dir) => (
                    <option key={dir} value={dir}>{dir}</option>
                  ))}
                  <option value="__new__">新增目錄</option>
                </select>
                {usingNewDirectory && (
                  <input
                    value={qaTargetDir}
                    onChange={(event) => setQaTargetDir(event.target.value)}
                    placeholder="例如：faq/customer"
                    className="w-full rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-950/60 dark:text-white dark:placeholder:text-slate-500"
                  />
                )}
              </div>

              <div className="space-y-3">
                {qaRows.map((row, index) => (
                  <div
                    key={index}
                    className="rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-950/40"
                  >
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                        Q&A {index + 1}
                      </span>
                      <button
                        type="button"
                        onClick={() => deleteRow(index)}
                        className="rounded-md p-1 text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
                        aria-label={`刪除第 ${index + 1} 列`}
                      >
                        <span className="material-symbols-outlined text-[1rem]">delete</span>
                      </button>
                    </div>
                    <div className="space-y-3">
                      <label className="block space-y-1.5">
                        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">問題</span>
                        <input
                          value={row.question}
                          onChange={(event) => updateRow(index, { question: event.target.value })}
                          placeholder="輸入問題"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-900/70 dark:text-white dark:placeholder:text-slate-500"
                        />
                      </label>
                      <label className="block space-y-1.5">
                        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">答案</span>
                        <textarea
                          value={row.answer}
                          onChange={(event) => updateRow(index, { answer: event.target.value })}
                          placeholder="輸入答案"
                          className="min-h-[7rem] w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-900/70 dark:text-white dark:placeholder:text-slate-500"
                        />
                      </label>
                    </div>
                  </div>
                ))}
              </div>

              <button
                type="button"
                onClick={() => setQaRows([...qaRows, createEmptyQaRow()])}
                className="inline-flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-4 py-2 text-sm font-semibold text-primary transition-colors hover:bg-primary/15"
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">add</span>
                新增列
              </button>
            </div>

            <div className="flex min-h-[18rem] flex-col rounded-xl border border-slate-200 bg-slate-950 text-slate-100 dark:border-slate-800">
              <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Markdown 預覽</span>
                <span className="text-xs text-slate-500">{markdownPreview.length.toLocaleString()} chars</span>
              </div>
              <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words px-4 py-3 text-sm leading-relaxed">
                {markdownPreview || "尚無可預覽內容"}
              </pre>
            </div>
          </div>

          <div className="mt-4 min-h-[1.25rem]">
            {hasInvalidTargetDir ? (
              <p className="text-xs font-medium text-amber-600 dark:text-amber-300">目錄不可為絕對路徑或包含 ..。</p>
            ) : hasIncompleteRows ? (
              <p className="text-xs font-medium text-amber-600 dark:text-amber-300">每列都需要同時有問題與答案。</p>
            ) : !hasUsableRow ? (
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">至少填寫一列完整 Q&A。</p>
            ) : null}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-4 dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onCreate}
            disabled={createDisabled}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">
              {creating ? "sync" : "save"}
            </span>
            {creating ? "建立中..." : "建立來源"}
          </button>
        </div>
      </div>
    </div>
  );
}

function isInvalidTargetDir(targetDir: string): boolean {
  const cleaned = targetDir.trim();
  if (!cleaned) {
    return false;
  }
  return cleaned.startsWith("/") || cleaned.split(/[\\/]+/).includes("..");
}
