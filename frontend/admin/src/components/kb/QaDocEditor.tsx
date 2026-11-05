import { useEffect, useRef, useState } from "react";

import {
  createEmptyQaRow,
  parseQaCsv,
  parseQaMarkdown,
  qaRowsToCsv,
  qaRowsToMarkdown,
  type QaRow,
} from "./qaMarkdown";
import QaRowCard, { QaRowListHeader } from "./qa/QaRowCard";
import { moveToInsertion, useRowReorder } from "./qa/rowReorder";

interface QaDocEditorProps {
  content: string;
  onChange: (content: string) => void;
  format?: "markdown" | "csv";
}

type EditableField = "question" | "answer" | "img" | "url" | "hidden";

/**
 * CSV 匯入時會依 index 排序，只換列的位置，下次同步就排回去了。沿用原本那組
 * 號碼依新順序重發，不重編成 1..N：拆成多檔的主題靠這些號碼記跨檔順序。
 */
function reassignCsvIndexes(rows: QaRow[]): QaRow[] {
  const indexes = rows.map((row) => row.csvFields?.index ?? "");
  if (indexes.some((index) => index.trim() === "" || !Number.isFinite(Number(index)))) return rows;
  const sorted = [...indexes].sort((a, b) => Number(a) - Number(b));
  return rows.map((row, position) => ({
    ...row,
    csvFields: { ...row.csvFields, index: sorted[position] },
  }));
}

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

  const reorder = useRowReorder(rows.length, (from, insertAt) => {
    emit(reassignCsvIndexes(moveToInsertion(rows, from, insertAt)));
  });

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
          <div className="divide-y divide-border rounded-xl border border-border bg-surface-raised">
            <QaRowListHeader />
            {rows.map((row, idx) => (
              <QaRowCard
                key={idx}
                index={idx}
                question={row.question}
                answer={row.answer}
                img={row.img}
                url={row.url}
                hidden={row.hidden}
                onChange={(field, value) => handleCellChange(idx, field, value)}
                onRemove={() => handleRemoveRow(idx)}
                rowProps={reorder.rowProps(idx)}
                handleProps={reorder.handleProps(idx)}
                dropLine={reorder.dropLine(idx)}
                dragging={reorder.isDragging(idx)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="px-4 pb-3 shrink-0">
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
