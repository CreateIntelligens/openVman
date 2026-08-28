import { useEffect, useRef, useState } from "react";

import {
  createEmptyQaRow,
  parseQaCsv,
  parseQaMarkdown,
  qaRowsToCsv,
  qaRowsToMarkdown,
  type QaRow,
} from "./qaMarkdown";
import QaImagePreview from "./QaImagePreview";

interface QaDocEditorProps {
  content: string;
  onChange: (content: string) => void;
  format?: "markdown" | "csv";
}

type EditableField = "question" | "answer" | "img" | "url" | "hidden";

function editableRowsFromContent(content: string, format: "markdown" | "csv"): QaRow[] {
  const parsedRows = format === "csv" ? parseQaCsv(content).rows : parseQaMarkdown(content);
  return parsedRows.length > 0 ? parsedRows : [createEmptyQaRow()];
}

export default function QaDocEditor({ content, onChange, format = "markdown" }: QaDocEditorProps) {
  const [rows, setRows] = useState<QaRow[]>(() => editableRowsFromContent(content, format));
  const csvHeadersRef = useRef(format === "csv" ? parseQaCsv(content).headers : []);
  // Blank draft rows serialize to nothing, so re-parse only on external
  // content changes (document switch / cancel), not on our own emits.
  const lastEmittedRef = useRef(content);

  useEffect(() => {
    if (content !== lastEmittedRef.current) {
      if (format === "csv") {
        const parsedCsv = parseQaCsv(content);
        const nextRows = parsedCsv.rows.length > 0
          ? parsedCsv.rows
          : [createEmptyQaRow()];
        setRows(nextRows);
        csvHeadersRef.current = parsedCsv.headers;
      } else {
        setRows(editableRowsFromContent(content, format));
        csvHeadersRef.current = [];
      }
      lastEmittedRef.current = content;
    }
  }, [content, format]);

  const emit = (next: QaRow[]) => {
    setRows(next);
    const serialized = format === "csv"
      ? qaRowsToCsv(next, csvHeadersRef.current)
      : qaRowsToMarkdown(next);
    lastEmittedRef.current = serialized;
    onChange(serialized);
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
          <div className="flex flex-col items-center justify-center h-full text-content-subtle py-12 space-y-2">
            <span className="material-symbols-outlined text-[2.5rem]">quiz</span>
            <p className="text-sm font-medium">此文件尚無任何問答內容</p>
            <p className="text-xs">點擊下方「新增一列」開始建立問答</p>
          </div>
        ) : (
          <div className="space-y-4">
            {rows.map((row, idx) => (
              <article
                key={idx}
                className={`rounded-xl border border-border bg-surface-raised p-4 shadow-sm transition-colors ${row.hidden ? "opacity-60" : ""}`}
              >
                <header className="mb-4 flex items-center justify-between gap-3">
                  <span className="text-xs font-semibold text-content-subtle">問答 {idx + 1}</span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleCellChange(idx, "hidden", !row.hidden)}
                      className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium ${row.hidden ? "bg-surface-sunken text-content-subtle " : "bg-success/10 text-success"}`}
                      title={row.hidden ? "目前已隱藏，點擊以顯示" : "目前顯示中，點擊以隱藏"}
                    >
                      <span className="material-symbols-outlined text-base">{row.hidden ? "visibility_off" : "visibility"}</span>
                      {row.hidden ? "已隱藏" : "顯示中"}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRemoveRow(idx)}
                      className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-content-subtle transition-colors hover:bg-danger/10 hover:text-danger"
                      title="刪除此行"
                    >
                      <span className="material-symbols-outlined text-base">delete</span>
                      刪除
                    </button>
                  </div>
                </header>
                <div className="grid gap-4 lg:grid-cols-2">
                  <label className="space-y-1.5 text-xs font-semibold text-content-subtle">
                    <span>問題</span>
                    <textarea
                      value={row.question}
                      onChange={(e) => handleCellChange(idx, "question", e.target.value)}
                      placeholder="請輸入問題"
                      rows={3}
                      className="w-full resize-y rounded-lg border border-border bg-surface p-3 text-sm font-normal leading-relaxed text-content outline-none transition-colors focus:border-primary focus:bg-white dark:bg-surface/40 dark:focus:bg-surface/70"
                    />
                  </label>
                  <label className="space-y-1.5 text-xs font-semibold text-content-subtle">
                    <span>答案</span>
                    <textarea
                      value={row.answer}
                      onChange={(e) => handleCellChange(idx, "answer", e.target.value)}
                      placeholder="請輸入答案"
                      rows={5}
                      className="w-full resize-y rounded-lg border border-border bg-surface p-3 text-sm font-normal leading-relaxed text-content outline-none transition-colors focus:border-primary focus:bg-white dark:bg-surface/40 dark:focus:bg-surface/70"
                    />
                  </label>
                </div>
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <label className="space-y-2 text-xs font-semibold text-content-subtle">
                    <span>圖片</span>
                    <QaImagePreview
                      imageId={row.img}
                      alt={`${row.question || `問答 ${idx + 1}`}的參考圖片`}
                    />
                    <input
                      type="text"
                      value={row.img}
                      onChange={(e) => handleCellChange(idx, "img", e.target.value)}
                      placeholder="圖片 ID"
                      className="w-full rounded-lg border border-border bg-surface p-2.5 font-mono text-xs font-normal text-content-muted outline-none focus:border-primary dark:bg-surface/40 "
                    />
                  </label>
                  <label className="space-y-2 text-xs font-semibold text-content-subtle">
                    <span>外部連結</span>
                    <input
                      type="text"
                      value={row.url}
                      onChange={(e) => handleCellChange(idx, "url", e.target.value)}
                      placeholder="外部連結"
                      className="w-full rounded-lg border border-border bg-surface p-2.5 text-xs font-normal text-content-muted outline-none focus:border-primary dark:bg-surface/40 "
                    />
                  </label>
                </div>
              </article>
            ))}
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
