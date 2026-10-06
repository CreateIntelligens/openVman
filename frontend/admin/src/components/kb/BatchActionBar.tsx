import { useMemo, useState } from "react";

import {
  deleteKnowledgeDocument,
  moveKnowledgeDocument,
  updateKnowledgeDocumentMeta,
  type KnowledgeDocumentSummary,
  type KnowledgeLanguage,
} from "../../api";
import type { Status } from "../../hooks/useStatusState";
import ConfirmModal from "../ConfirmModal";
import {
  fileNameOf,
  formatBatchSummary,
  isUploadDerivedKnowledgeFile,
  KNOWLEDGE_LANGUAGE_LABELS,
  parentDirOf,
  runBatchSequentially,
} from "./helpers";
import MoveModal from "./MoveModal";
import { useModalDismiss } from "./useModalDismiss";

export type BatchActionKind = "move" | "delete" | "language";

const LISTED_NAME_LIMIT = 5;

const LANGUAGE_CHOICES: { value: KnowledgeLanguage | "auto"; label: string }[] = [
  { value: "auto", label: "自動（依內容判斷）" },
  ...(Object.entries(KNOWLEDGE_LANGUAGE_LABELS) as [KnowledgeLanguage, string][]).map(
    ([value, label]) => ({ value, label }),
  ),
];

const ACTION_BUTTON_CLASS =
  "flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-content-muted transition-colors hover:bg-surface-sunken hover:text-content disabled:pointer-events-none disabled:opacity-40";

function BatchLanguageModal({
  count,
  onApply,
  onClose,
}: {
  count: number;
  onApply: (language: KnowledgeLanguage | "auto") => void;
  onClose: () => void;
}) {
  const [language, setLanguage] = useState<KnowledgeLanguage | "auto">("auto");
  const dismiss = useModalDismiss(onClose);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      {...dismiss}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="批次設定語言"
        className="mx-4 flex max-h-[70vh] w-full max-w-sm flex-col rounded-2xl border border-border bg-surface-raised shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-5 py-4">
          <span className="material-symbols-outlined text-[1.25rem] text-primary">translate</span>
          <span className="text-sm font-semibold text-content">設定 {count} 個檔案的語言</span>
        </div>
        <div className="flex-1 overflow-y-auto py-2" role="radiogroup" aria-label="文件語言">
          {LANGUAGE_CHOICES.map((choice) => {
            const selected = choice.value === language;
            return (
              <button
                key={choice.value}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setLanguage(choice.value)}
                className={`flex w-full items-center gap-2 px-5 py-2.5 text-left text-sm transition-colors ${
                  selected ? "bg-primary/10 text-primary" : "text-content-muted hover:bg-surface-sunken"
                }`}
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">
                  {selected ? "radio_button_checked" : "radio_button_unchecked"}
                </span>
                {choice.label}
              </button>
            );
          })}
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
          <button type="button" onClick={onClose} className="btn btn-ghost">
            取消
          </button>
          <button type="button" onClick={() => onApply(language)} className="btn btn-primary">
            套用
          </button>
        </div>
      </div>
    </div>
  );
}

export default function BatchActionBar({
  selectedPaths,
  documents,
  serverDirs,
  onClearSelection,
  onSelectionChange,
  onFinished,
  onStatus,
  onRunningChange,
}: {
  selectedPaths: string[];
  documents: KnowledgeDocumentSummary[];
  serverDirs: string[];
  onClearSelection: () => void;
  onSelectionChange: (paths: string[]) => void;
  onFinished: (
    action: BatchActionKind,
    succeeded: string[],
    targetPathOf: (path: string) => string,
  ) => Promise<void> | void;
  onStatus: (status: Status) => void;
  onRunningChange?: (running: boolean) => void;
}) {
  const [dialog, setDialog] = useState<BatchActionKind | null>(null);
  const [progress, setProgress] = useState<{ label: string; done: number; total: number } | null>(null);
  const documentsByPath = useMemo(
    () => new Map(documents.map((document) => [document.path, document])),
    [documents],
  );
  const count = selectedPaths.length;
  const running = progress !== null;

  const runBatch = async (
    action: BatchActionKind,
    label: string,
    paths: string[],
    perFile: (path: string) => Promise<unknown>,
    options: { note?: string; targetPathOf?: (path: string) => string } = {},
  ) => {
    setDialog(null);
    onStatus(null);
    setProgress({ label, done: 0, total: paths.length });
    onRunningChange?.(true);
    try {
      const result = await runBatchSequentially(paths, perFile, (done, total) =>
        setProgress({ label, done, total }),
      );
      // 失敗的留著勾選，修正原因後可直接重試。
      onSelectionChange(result.failed.map((failure) => failure.path));
      await onFinished(action, result.succeeded, options.targetPathOf ?? ((path) => path));
      onStatus({
        type: result.failed.length > 0 ? "error" : "success",
        message: formatBatchSummary(label, result, options.note),
      });
    } finally {
      setProgress(null);
      onRunningChange?.(false);
    }
  };

  const handleMove = (targetDir: string) => {
    const targetPathOf = (path: string) =>
      targetDir ? `${targetDir}/${fileNameOf(path)}` : fileNameOf(path);
    const pending = selectedPaths.filter((path) => parentDirOf(path) !== targetDir);
    const alreadyThere = count - pending.length;
    void runBatch(
      "move",
      "移動",
      pending,
      async (path) => {
        if (documentsByPath.get(path)?.qa_attached) {
          throw new Error("已掛在快速問答樹上，不能移動");
        }
        await moveKnowledgeDocument(path, targetPathOf(path));
      },
      {
        note: alreadyThere > 0 ? `${alreadyThere} 個原本就在目標資料夾` : undefined,
        targetPathOf,
      },
    );
  };

  const handleDelete = () => {
    void runBatch("delete", "刪除", [...selectedPaths], (path) => deleteKnowledgeDocument(path));
  };

  const handleLanguage = (language: KnowledgeLanguage | "auto") => {
    void runBatch("language", "語言設定", [...selectedPaths], async (path) => {
      if (documentsByPath.get(path)?.is_indexable === false) {
        throw new Error("這類檔案不支援語言設定");
      }
      await updateKnowledgeDocumentMeta(path, { language });
    });
  };

  const deleteMessage = useMemo(() => {
    const listed = selectedPaths.slice(0, LISTED_NAME_LIMIT).map((path) => `• ${fileNameOf(path)}`);
    const rest = count - LISTED_NAME_LIMIT;
    const selectedDocs = selectedPaths.flatMap((path) => documentsByPath.get(path) ?? []);
    const qaAttachedCount = selectedDocs.filter(
      (document) => document.source_type === "qa" && document.qa_attached,
    ).length;
    const notes = [
      qaAttachedCount > 0
        ? `其中 ${qaAttachedCount} 個掛在快速問答樹上，對應的節點與題目會一併移除。`
        : "",
      selectedDocs.some(isUploadDerivedKnowledgeFile)
        ? "上傳產生的檔案只會移除知識文件與索引，原始上傳檔仍保留在 raw/。"
        : "",
    ].filter(Boolean);
    return [
      `確定要刪除 ${count} 個檔案嗎？`,
      ...listed,
      ...(rest > 0 ? [`…另有 ${rest} 個`] : []),
      ...(notes.length > 0 ? ["", ...notes] : []),
    ].join("\n");
  }, [count, documentsByPath, selectedPaths]);

  return (
    <div className="border-b border-border bg-primary/5 px-3 py-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-content-muted" aria-live="polite">
          已選 {count} 個檔案
        </span>
        <button
          type="button"
          onClick={onClearSelection}
          disabled={running || count === 0}
          className="rounded-md px-1.5 py-0.5 text-content-subtle transition-colors hover:bg-surface-sunken hover:text-content disabled:pointer-events-none disabled:opacity-40"
        >
          全部取消
        </button>
      </div>
      {running ? (
        <div className="mt-2" role="status">
          <div className="flex items-center gap-1.5 text-xs text-primary">
            <span aria-hidden="true" className="material-symbols-outlined animate-spin text-[1rem]">sync</span>
            {progress.label}中 {progress.done}/{progress.total}
          </div>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-border">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }}
            />
          </div>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1">
          <button
            type="button"
            className={ACTION_BUTTON_CLASS}
            disabled={count === 0}
            onClick={() => setDialog("move")}
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">drive_file_move</span>
            移動到…
          </button>
          <button
            type="button"
            className={ACTION_BUTTON_CLASS}
            disabled={count === 0}
            onClick={() => setDialog("language")}
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">translate</span>
            設定語言
          </button>
          <button
            type="button"
            className={`${ACTION_BUTTON_CLASS} hover:border-danger/40 hover:bg-danger/10 hover:text-danger`}
            disabled={count === 0}
            onClick={() => setDialog("delete")}
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">delete</span>
            刪除
          </button>
        </div>
      )}

      {dialog === "move" && (
        <MoveModal
          sourcePaths={selectedPaths}
          allDocuments={documents}
          serverDirs={serverDirs}
          onMove={handleMove}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog === "language" && (
        <BatchLanguageModal count={count} onApply={handleLanguage} onClose={() => setDialog(null)} />
      )}

      <ConfirmModal
        open={dialog === "delete"}
        title="批次刪除文件"
        message={deleteMessage}
        confirmLabel={`刪除 ${count} 個`}
        danger
        onConfirm={handleDelete}
        onCancel={() => setDialog(null)}
      />
    </div>
  );
}
