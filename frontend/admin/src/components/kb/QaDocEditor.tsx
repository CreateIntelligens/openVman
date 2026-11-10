import { useEffect, useRef, useState } from "react";

import {
  createEmptyQaRow,
  parseQaCsv,
  parseQaMarkdown,
  qaRowsToCsv,
  qaRowsToMarkdown,
  type QaRow,
} from "./qaMarkdown";
import QaRowCard, { QA_HIDDEN_HINT, QaRowListHeader } from "./qa/QaRowCard";
import QaMoveToModal from "./qa/QaMoveToModal";
import { insertionForPosition, moveToInsertion, useRowReorder } from "./qa/rowReorder";
import { useQaImageUpload } from "./qa/useQaImageUpload";
import { useQaRowReveal } from "./qa/useQaRowReveal";

interface QaDocEditorProps {
  content: string;
  onChange: (content: string) => void;
  format?: "markdown" | "csv";
}

type EditableField = "question" | "answer" | "img" | "url" | "hidden";

/** 列表用的 id：刪除、排序時列的展開狀態要跟著列走，上傳完也要找得到原本那一列。 */
type EditorRow = QaRow & { localId: string };

let nextLocalId = 0;

function withLocalId(row: QaRow): EditorRow {
  nextLocalId += 1;
  return { ...row, localId: `qa_doc_row_${nextLocalId}` };
}

/**
 * CSV 匯入時會依 index 排序，只換列的位置，下次同步就排回去了。沿用原本那組
 * 號碼依新順序重發，不重編成 1..N：拆成多檔的主題靠這些號碼記跨檔順序。
 */
function reassignCsvIndexes<T extends QaRow>(rows: T[]): T[] {
  const indexes = rows.map((row) => row.csvFields?.index ?? "");
  if (indexes.some((index) => index.trim() === "" || !Number.isFinite(Number(index)))) return rows;
  const sorted = [...indexes].sort((a, b) => Number(a) - Number(b));
  return rows.map((row, position) => ({
    ...row,
    csvFields: { ...row.csvFields, index: sorted[position] },
  }));
}

function editableRowsFromContent(content: string, format: "markdown" | "csv"): EditorRow[] {
  const parsedRows = format === "csv" ? parseQaCsv(content).rows : parseQaMarkdown(content);
  return (parsedRows.length > 0 ? parsedRows : [createEmptyQaRow()]).map(withLocalId);
}

export default function QaDocEditor({ content, onChange, format = "markdown" }: QaDocEditorProps) {
  const [rows, setRows] = useState<EditorRow[]>(() => editableRowsFromContent(content, format));
  const [moveToRowId, setMoveToRowId] = useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = useState<{ error: boolean; text: string } | null>(null);
  const csvHeadersRef = useRef(format === "csv" ? parseQaCsv(content).headers : []);
  // Blank draft rows serialize to nothing, so re-parse only on external
  // content changes (document switch / cancel), not on our own emits.
  const lastEmittedRef = useRef(content);
  // 上傳完才寫回圖片編號，這段時間使用者可能又改了別列，要拿最新的清單。
  const rowsRef = useRef(rows);
  rowsRef.current = rows;

  const { revealRow, registerRow, flashRowId } = useQaRowReveal();

  useEffect(() => {
    if (content !== lastEmittedRef.current) {
      setRows(editableRowsFromContent(content, format));
      csvHeadersRef.current = format === "csv" ? parseQaCsv(content).headers : [];
      lastEmittedRef.current = content;
    }
  }, [content, format]);

  const emit = (next: EditorRow[]) => {
    rowsRef.current = next;
    setRows(next);
    const serialized = format === "csv"
      ? qaRowsToCsv(next, csvHeadersRef.current)
      : qaRowsToMarkdown(next);
    lastEmittedRef.current = serialized;
    onChange(serialized);
  };

  const imageUpload = useQaImageUpload({
    onUploaded: (rowId, imageId) => {
      if (!rowsRef.current.some((row) => row.localId === rowId)) return;
      emit(rowsRef.current.map((row) => (row.localId === rowId ? { ...row, img: imageId } : row)));
      setUploadMessage({ error: false, text: "圖片已上傳，編號已經填好。" });
    },
    onError: (text) => setUploadMessage({ error: true, text }),
  });
  const uploading = imageUpload.uploadingRowId !== null;

  const handlePickImage = (rowId: string) => {
    setUploadMessage(null);
    imageUpload.pickImage(rowId);
  };

  const handleCellChange = (
    rowId: string,
    field: EditableField,
    value: string | boolean,
  ) => {
    emit(rowsRef.current.map((row) => (row.localId === rowId ? { ...row, [field]: value } : row)));
  };

  const handleAddRow = () => {
    const newRow = withLocalId(createEmptyQaRow());
    emit([...rowsRef.current, newRow]);
    revealRow({ rowId: newRow.localId, focus: "question", flash: true });
  };

  const handleRemoveRow = (rowId: string) => {
    emit(rowsRef.current.filter((row) => row.localId !== rowId));
  };

  const moveRowTo = (rowId: string, position: number) => {
    const from = rowsRef.current.findIndex((row) => row.localId === rowId);
    if (from < 0) return;
    emit(reassignCsvIndexes(moveToInsertion(rowsRef.current, from, insertionForPosition(from, position))));
    revealRow({ rowId, flash: true });
  };

  const reorder = useRowReorder(rows.length, (from, insertAt) => {
    emit(reassignCsvIndexes(moveToInsertion(rowsRef.current, from, insertAt)));
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3">
        <button type="button" onClick={handleAddRow} className="btn btn-ghost">
          <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">add</span>
          新增問題
        </button>
        {uploadMessage && (
          <p
            role={uploadMessage.error ? "alert" : "status"}
            className={`min-w-0 text-xs ${uploadMessage.error ? "text-danger" : "text-content-muted"}`}
          >
            {uploadMessage.text}
          </p>
        )}
      </div>

      {/* 底部留白：小助理固定在右下角，最後一列要捲得出來。 */}
      <div className="min-h-0 flex-1 overflow-auto px-4 pb-24 pt-2">
        {rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <p className="text-sm font-medium text-content">這份文件還沒有問題</p>
            <p className="mt-1 text-sm text-content-muted">按上面的「新增問題」開始輸入。</p>
          </div>
        ) : (
          <>
            <p className="pb-2 text-xs text-content-muted">{QA_HIDDEN_HINT}</p>
            <div className="divide-y divide-border rounded-xl border border-border bg-surface-raised">
              <QaRowListHeader />
              {rows.map((row, idx) => (
                <QaRowCard
                  key={row.localId}
                  index={idx}
                  question={row.question}
                  answer={row.answer}
                  img={row.img}
                  url={row.url}
                  hidden={row.hidden}
                  onMoveUp={() => moveRowTo(row.localId, idx)}
                  onMoveDown={() => moveRowTo(row.localId, idx + 2)}
                  onMoveTo={rows.length > 1 ? () => setMoveToRowId(row.localId) : undefined}
                  isFirst={idx === 0}
                  isLast={idx === rows.length - 1}
                  onChange={(field, value) => handleCellChange(row.localId, field, value)}
                  onRemove={() => handleRemoveRow(row.localId)}
                  onPickImage={() => handlePickImage(row.localId)}
                  uploadingImage={imageUpload.uploadingRowId === row.localId}
                  uploadDisabled={uploading}
                  rowRef={(element) => registerRow(row.localId, element)}
                  highlighted={flashRowId === row.localId}
                  rowProps={reorder.rowProps(idx)}
                  handleProps={reorder.handleProps(idx)}
                  dropLine={reorder.dropLine(idx)}
                  dragging={reorder.isDragging(idx)}
                />
              ))}
            </div>
          </>
        )}
      </div>

      <input {...imageUpload.fileInputProps} />
      {moveToRowId !== null && rows.some((row) => row.localId === moveToRowId) && (
        <QaMoveToModal
          rowNumber={rows.findIndex((row) => row.localId === moveToRowId) + 1}
          total={rows.length}
          onMove={(position) => {
            moveRowTo(moveToRowId, position);
            setMoveToRowId(null);
          }}
          onClose={() => setMoveToRowId(null)}
        />
      )}
    </div>
  );
}
