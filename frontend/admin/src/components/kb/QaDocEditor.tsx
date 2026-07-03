import { useEffect, useRef, useState } from "react";

import {
  createEmptyQaRow,
  parseQaMarkdown,
  qaRowsToMarkdown,
  type QaRow,
} from "./qaMarkdown";

interface QaDocEditorProps {
  content: string;
  onChange: (content: string) => void;
}

type EditableField = "question" | "answer" | "img" | "url" | "hidden";

function editableRowsFromContent(content: string): QaRow[] {
  const parsedRows = parseQaMarkdown(content);
  return parsedRows.length > 0 ? parsedRows : [createEmptyQaRow()];
}

export default function QaDocEditor({ content, onChange }: QaDocEditorProps) {
  const [rows, setRows] = useState<QaRow[]>(() => editableRowsFromContent(content));
  // Blank draft rows serialize to nothing, so re-parse only on external
  // content changes (document switch / cancel), not on our own emits.
  const lastEmittedRef = useRef(content);

  useEffect(() => {
    if (content !== lastEmittedRef.current) {
      setRows(editableRowsFromContent(content));
      lastEmittedRef.current = content;
    }
  }, [content]);

  const emit = (next: QaRow[]) => {
    setRows(next);
    const markdown = qaRowsToMarkdown(next);
    lastEmittedRef.current = markdown;
    onChange(markdown);
  };

  const handleCellChange = (
    index: number,
    field: EditableField,
    value: string | boolean,
  ) => {
    emit(rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  };

  const handleAddRow = () => {
    emit([...rows, createEmptyQaRow()]);
  };

  const handleRemoveRow = (index: number) => {
    emit(rows.filter((_, i) => i !== index));
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex-1 overflow-auto p-4 min-h-0">
        {rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-slate-500 py-12 space-y-2">
            <span className="material-symbols-outlined text-[2.5rem]">quiz</span>
            <p className="text-sm font-medium">此文件尚無任何問答內容</p>
            <p className="text-xs">點擊下方「新增一列」開始建立問答</p>
          </div>
        ) : (
          <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden min-w-[50rem]">
            <table className="w-full text-left border-collapse table-fixed">
              <thead>
                <tr className="bg-slate-50 dark:bg-slate-950/50 border-b border-slate-200 dark:border-slate-800 text-xs font-bold text-slate-500 dark:text-slate-400">
                  <th className="py-3 px-4 w-[4%] text-center">#</th>
                  <th className="py-3 px-4 w-[28%]">問題 (Question)</th>
                  <th className="py-3 px-4 w-[28%]">答案 (Answer)</th>
                  <th className="py-3 px-4 w-[12%]">圖片 ID</th>
                  <th className="py-3 px-4 w-[12%]">外部連結 URL</th>
                  <th className="py-3 px-4 w-[8%] text-center">可見性</th>
                  <th className="py-3 px-4 w-[8%] text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-sm">
                {rows.map((row, idx) => (
                  <tr
                    key={idx}
                    className={`hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors ${
                      row.hidden ? "opacity-60 bg-slate-50/20 dark:bg-slate-950/10" : ""
                    }`}
                  >
                    <td className="py-2.5 px-4 text-center text-xs font-mono text-slate-400 dark:text-slate-500">
                      {idx + 1}
                    </td>

                    <td className="py-2 px-3 align-top">
                      <textarea
                        value={row.question}
                        onChange={(e) => handleCellChange(idx, "question", e.target.value)}
                        placeholder="請輸入問題"
                        rows={2}
                        className="w-full resize-none bg-transparent outline-none focus:bg-white dark:focus:bg-slate-850 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs leading-relaxed text-slate-800 dark:text-slate-200 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 align-top">
                      <textarea
                        value={row.answer}
                        onChange={(e) => handleCellChange(idx, "answer", e.target.value)}
                        placeholder="請輸入答案"
                        rows={2}
                        className="w-full resize-none bg-transparent outline-none focus:bg-white dark:focus:bg-slate-850 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs leading-relaxed text-slate-800 dark:text-slate-200 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 align-top">
                      <input
                        type="text"
                        value={row.img}
                        onChange={(e) => handleCellChange(idx, "img", e.target.value)}
                        placeholder="圖片 ID"
                        className="w-full min-w-0 bg-transparent outline-none focus:bg-white dark:focus:bg-slate-850 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs font-mono text-slate-700 dark:text-slate-300 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 align-top">
                      <input
                        type="text"
                        value={row.url}
                        onChange={(e) => handleCellChange(idx, "url", e.target.value)}
                        placeholder="外部連結"
                        className="w-full bg-transparent outline-none focus:bg-white dark:focus:bg-slate-850 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs text-slate-700 dark:text-slate-300 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 text-center align-middle">
                      <button
                        type="button"
                        onClick={() => handleCellChange(idx, "hidden", !row.hidden)}
                        className={`inline-flex items-center justify-center p-1.5 rounded-lg transition-colors ${
                          row.hidden
                            ? "bg-slate-100 hover:bg-slate-200 text-slate-400 dark:bg-slate-800 dark:hover:bg-slate-700"
                            : "bg-success/10 text-success hover:bg-success/20 dark:bg-success/20 dark:text-success"
                        }`}
                        title={row.hidden ? "目前已隱藏，點擊以顯示" : "目前顯示中，點擊以隱藏"}
                      >
                        <span className="material-symbols-outlined text-[1.125rem]">
                          {row.hidden ? "visibility_off" : "visibility"}
                        </span>
                      </button>
                    </td>

                    <td className="py-2 px-3 text-center align-middle">
                      <button
                        type="button"
                        onClick={() => handleRemoveRow(idx)}
                        className="inline-flex items-center justify-center p-1.5 rounded-lg text-slate-400 hover:text-danger hover:bg-danger/10 transition-all"
                        title="刪除此行"
                      >
                        <span className="material-symbols-outlined text-[1.125rem]">delete</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="px-4 pb-4 shrink-0">
        <button
          type="button"
          onClick={handleAddRow}
          className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2 text-xs font-semibold text-primary transition-colors hover:bg-primary/10"
        >
          <span className="material-symbols-outlined text-[1.1rem]">add</span>
          新增一列
        </button>
      </div>
    </div>
  );
}
