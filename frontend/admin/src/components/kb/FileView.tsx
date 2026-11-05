import { useState, useSyncExternalStore, type ReactNode } from "react";

import type { KnowledgeDocument, KnowledgeDocumentSummary, KnowledgeLanguage } from "../../api";
import { useLocalStorageState } from "../../hooks/useLocalStorageState";
import ActionMenu, { type ActionMenuGroup } from "../ActionMenu";
import ConfirmModal from "../ConfirmModal";
import MarkdownPreview from "../MarkdownPreview";
import SegmentedControl from "../SegmentedControl";
import Select from "../Select";
import {
  displayDocumentPath,
  fileNameOf,
  formatDate,
  formatSize,
  KNOWLEDGE_LANGUAGE_LABELS,
} from "./helpers";
import QaDocEditor from "./QaDocEditor";
import SourceBadge from "./SourceBadge";
import { documentStatusLabel, type DocumentStatusLabel } from "./StatusDot";

type DocView = "edit" | "preview" | "split";
type QaView = "table" | "raw";

const DOC_VIEW_STORAGE_KEY = "admin.knowledge.doc_view";
const DOC_VIEW_IDS: readonly DocView[] = ["edit", "preview", "split"];
const DOC_VIEW_OPTIONS: { id: DocView; label: string }[] = [
  { id: "edit", label: "編輯" },
  { id: "preview", label: "預覽" },
  { id: "split", label: "並排" },
];
const NARROW_DOC_VIEW_OPTIONS = DOC_VIEW_OPTIONS.filter((option) => option.id !== "split");
const QA_VIEW_OPTIONS: { id: QaView; label: string }[] = [
  { id: "table", label: "問答表" },
  { id: "raw", label: "原始文字" },
];

const LANGUAGE_OPTIONS = Object.entries(KNOWLEDGE_LANGUAGE_LABELS).map(([value, label]) => ({ value, label }));

const STATUS_DOT_CLASS: Record<DocumentStatusLabel, string> = {
  可被搜尋: "bg-success",
  處理中: "animate-pulse bg-warn",
  已停用: "bg-border-strong",
  不會被搜尋: "bg-border-strong",
};

// 按鈕本身的 .btn:disabled 是半透明，陶土底配白字只剩 1.8:1；換成灰底深字才看得清楚。
const SAVE_BUTTON_CLASS =
  "btn btn-primary disabled:border-border disabled:bg-surface-sunken disabled:text-content-muted disabled:opacity-100";
const TEXTAREA_CLASS =
  "min-h-0 w-full flex-1 resize-none overflow-auto bg-transparent p-4 font-mono text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/40";

// 和 Tailwind 的 md 同一個斷點。比這窄時兩欄都擠不下，一次只顯示一個。
const SPLIT_VIEW_MEDIA_QUERY = "(min-width: 48rem)";

function subscribeToSplitWidth(onChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(SPLIT_VIEW_MEDIA_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function readHasSplitWidth(): boolean {
  return typeof window.matchMedia !== "function" || window.matchMedia(SPLIT_VIEW_MEDIA_QUERY).matches;
}

function PaneHeading({ children }: { children: ReactNode }) {
  return (
    <div className="shrink-0 border-b border-border bg-surface px-3 py-1.5 text-xs font-semibold text-content-muted dark:bg-surface/20">
      {children}
    </div>
  );
}

export default function FileView({
  document,
  editContent,
  setEditContent,
  loading,
  saving,
  dirty,
  onSave,
  onClose,
  onDelete,
  onMove,
  onToggleEnabled,
  onChangeLanguage,
  onRenormalize,
  onOpenQaTree,
  renormalizing,
}: {
  document: KnowledgeDocument | null;
  editContent: string;
  setEditContent: (c: string) => void;
  loading: boolean;
  saving: boolean;
  dirty: boolean;
  onSave: () => void;
  onClose: () => void;
  onDelete: (path: string) => void;
  onMove: (path: string) => void;
  onToggleEnabled: (doc: KnowledgeDocumentSummary) => void;
  onChangeLanguage?: (doc: KnowledgeDocumentSummary, language: KnowledgeLanguage | "auto") => void;
  onRenormalize?: (path: string) => void;
  onOpenQaTree?: () => void;
  renormalizing?: boolean;
}) {
  // 預設並排維持桌面原本的樣子；手機沒有並排，會當成預覽。
  const [storedView, setStoredView] = useLocalStorageState<DocView>(DOC_VIEW_STORAGE_KEY, "split", DOC_VIEW_IDS);
  const hasSplitWidth = useSyncExternalStore(subscribeToSplitWidth, readHasSplitWidth);
  // 記的是哪一份文件開著原始文字，換文件就回到問答表，不會讓人卡在看不懂的畫面。
  const [qaRawPath, setQaRawPath] = useState<string | null>(null);
  const [pendingLeave, setPendingLeave] = useState<(() => void) | null>(null);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-content-subtle">
        <span aria-hidden="true" className="material-symbols-outlined animate-spin mr-2">refresh</span> 載入中...
      </div>
    );
  }

  if (!document) {
    return (
      <div className="flex-1 flex items-center justify-center text-content-subtle">
        <span aria-hidden="true" className="material-symbols-outlined text-3xl mr-2">description</span> 選擇一個文件
      </div>
    );
  }

  const leaveThen = (action: () => void) => {
    if (dirty) {
      setPendingLeave(() => action);
    } else {
      action();
    }
  };

  const displayName = document.title || fileNameOf(document.path);
  const displayPath = displayDocumentPath(document.path);
  const statusLabel = documentStatusLabel(document);
  const isQaDocument = document.source_type === "qa";
  const isQaAttached = isQaDocument && document.qa_attached === true;
  const qaView: QaView = qaRawPath === document.path ? "raw" : "table";
  const view: DocView = storedView === "split" && !hasSplitWidth ? "preview" : storedView;
  const isSplit = view === "split";

  // 移動與 AI 整理完都會重新載入文件，還沒存的修改會被蓋掉，所以要先存。
  const unsavedReason = dirty ? "請先儲存目前的修改" : undefined;
  const menuGroups: ActionMenuGroup[] = [
    {
      id: "edit",
      items: [
        ...(!document.is_core && !isQaAttached
          ? [{
              id: "move",
              label: "移動…",
              disabledReason: unsavedReason,
              onSelect: () => onMove(document.path),
            }]
          : []),
        ...(!isQaAttached && onRenormalize
          ? [{
              id: "renormalize",
              label: "AI 整理排版",
              disabledReason: renormalizing ? "正在整理，請稍候" : unsavedReason,
              onSelect: () => onRenormalize(document.path),
            }]
          : []),
      ],
    },
    {
      id: "danger",
      items: document.is_core
        ? []
        : [{
            id: "delete",
            label: isQaAttached ? "刪除（連同快速問答的分類）" : "刪除",
            danger: true,
            onSelect: () => onDelete(document.path),
          }],
    },
  ];

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="shrink-0 space-y-2 border-b border-border bg-surface-raised px-3 py-2 dark:bg-surface/30 sm:px-4">
        <div className="flex items-center gap-3">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
            <div className="flex min-w-0 max-w-full items-center gap-1">
              {/* 桌面版左邊的樹一直都在，只有手機需要這顆才回得去。 */}
              <button
                type="button"
                onClick={() => leaveThen(onClose)}
                aria-label="返回"
                className="-ml-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-content-muted transition-colors hover:bg-surface-sunken hover:text-content md:hidden"
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[1.25rem]">arrow_back</span>
              </button>
              <h2 title={fileNameOf(document.path)} className="truncate text-base font-semibold text-content">
                {displayName}
              </h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-content-muted">
                <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT_CLASS[statusLabel]}`} />
                {statusLabel}
              </span>
              <SourceBadge sourceType={document.source_type} />
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {/* 先留好寬度，「未儲存」出現時不會把旁邊的東西推開。 */}
            <span aria-live="polite" className="w-[2.5rem] whitespace-nowrap text-right text-xs font-semibold text-warn">
              {dirty ? "未儲存" : ""}
            </span>
            <button
              type="button"
              onClick={onSave}
              disabled={saving || !dirty}
              className={SAVE_BUTTON_CLASS}
            >
              <span aria-hidden="true" className={`material-symbols-outlined text-[1rem] ${saving ? "animate-spin" : ""}`}>
                {saving ? "sync" : "save"}
              </span>
              {saving ? "儲存中…" : "儲存"}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {onChangeLanguage && document.is_indexable && (
            <Select
              label="語言"
              ariaLabel="文件語言"
              className="max-w-full"
              value={document.language_source === "manual" ? document.language ?? "auto" : "auto"}
              onChange={(value) => onChangeLanguage(document, value as KnowledgeLanguage | "auto")}
              options={[
                { value: "auto", label: `自動（${KNOWLEDGE_LANGUAGE_LABELS[document.language ?? "zh"]}）` },
                ...LANGUAGE_OPTIONS,
              ]}
            />
          )}

          {/* 不會被搜尋的文件 AI 本來就用不到，這個開關講的話會是錯的。 */}
          {document.is_indexable && (
            <button
              type="button"
              role="switch"
              aria-checked={document.enabled}
              onClick={() => onToggleEnabled(document)}
              className={`inline-flex items-center gap-2 whitespace-nowrap rounded-md py-1 text-sm font-medium transition-colors ${
                document.enabled ? "text-content" : "text-content-muted"
              }`}
            >
              <span
                aria-hidden="true"
                className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
                  document.enabled ? "bg-success" : "bg-border-strong"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-content-inverse transition-transform ${
                    document.enabled ? "translate-x-4" : "translate-x-0.5"
                  }`}
                />
              </span>
              {document.enabled ? "AI 會參考這份文件" : "已停用，AI 不會參考"}
            </button>
          )}

          {isQaDocument && onOpenQaTree && (
            <button type="button" onClick={() => leaveThen(onOpenQaTree)} className="btn btn-ghost">
              <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">quiz</span>
              前往快速問答
            </button>
          )}

          <ActionMenu label={displayName} triggerLabel="更多" triggerIcon="more_horiz" groups={menuGroups} />

          {renormalizing && (
            <span role="status" className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-content-muted">
              <span aria-hidden="true" className="material-symbols-outlined animate-spin text-[1rem] text-primary">sync</span>
              AI 整理中…
            </span>
          )}

          <div className="max-w-full md:ml-auto">
            {isQaDocument ? (
              <SegmentedControl
                label="問答文件的檢視方式"
                options={QA_VIEW_OPTIONS}
                value={qaView}
                onChange={(next) => setQaRawPath(next === "raw" ? document.path : null)}
              />
            ) : (
              <SegmentedControl
                label="文件的檢視方式"
                options={hasSplitWidth ? DOC_VIEW_OPTIONS : NARROW_DOC_VIEW_OPTIONS}
                value={view}
                onChange={setStoredView}
              />
            )}
          </div>
        </div>
      </div>

      {isQaDocument ? (
        <div className="flex-1 flex min-h-0 flex-col overflow-hidden">
          {isQaAttached && (
            <p className="shrink-0 border-b border-border bg-surface px-3 py-1.5 text-xs text-content-muted dark:bg-surface/20">
              這份文件屬於快速問答的分類，儲存後分類裡的題目會跟著更新。
            </p>
          )}
          {qaView === "raw" ? (
            <textarea
              aria-label="問答原始文字"
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className={TEXTAREA_CLASS}
              spellCheck={false}
            />
          ) : (
            <QaDocEditor
              content={editContent}
              onChange={setEditContent}
              format={document.extension?.toLowerCase() === ".csv" ? "csv" : "markdown"}
            />
          )}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {view !== "preview" && (
            <div className={`flex min-h-0 min-w-0 flex-1 flex-col ${isSplit ? "border-r border-border" : ""}`}>
              {isSplit && <PaneHeading>編輯</PaneHeading>}
              <textarea
                aria-label="文件內容"
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className={TEXTAREA_CLASS}
                spellCheck={false}
              />
            </div>
          )}

          {view !== "edit" && (
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              {isSplit && <PaneHeading>預覽</PaneHeading>}
              {/* 爬回來的網頁常有很長的網址，不斷行的話整個預覽都要橫向捲動。 */}
              <div className="flex-1 overflow-y-auto break-words p-4 prose-container">
                <MarkdownPreview content={editContent} />
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-0.5 border-t border-border bg-surface-raised px-4 py-1.5 text-xs text-content-muted dark:bg-surface/30">
        <span title={displayPath} className="min-w-0 flex-1 basis-[10rem] truncate">{displayPath}</span>
        <span className="hidden shrink-0 sm:inline">{document.extension || "—"}</span>
        <span className="hidden shrink-0 sm:inline">{formatSize(document.size)}</span>
        <span className="shrink-0">{formatDate(document.updated_at)}</span>
        {document.source_url && (
          <span title={document.source_url} className="min-w-0 flex-1 basis-[10rem] truncate text-info">
            {document.source_url}
          </span>
        )}
      </div>

      <ConfirmModal
        open={pendingLeave !== null}
        title="修改還沒儲存"
        message="離開這份文件後，還沒儲存的修改會消失。"
        confirmLabel="不儲存，離開"
        danger
        onConfirm={() => {
          setPendingLeave(null);
          pendingLeave?.();
        }}
        onCancel={() => setPendingLeave(null)}
      />
    </div>
  );
}
