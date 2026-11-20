import type { KnowledgeDocumentSummary, QaSyncState } from "../../api";

export type DocumentStatusLabel = "已停用" | "可被搜尋" | "處理中" | "不會被搜尋";

export const QA_SYNC_FAILED_HINT =
  "AI 暫時查不到這個分類的最新內容，請稍後再試，持續失敗請聯絡專人。";

export const QA_SYNC_STATUS_LABELS: Record<QaSyncState, string> = {
  synced: "已同步",
  updating: "更新中",
  failed: "同步失敗",
};

const QA_SYNC_STATUS_STYLES: Record<QaSyncState, { dotClass: string; textClass: string }> = {
  synced: { dotClass: "bg-success", textClass: "text-content-muted" },
  updating: { dotClass: "bg-warn animate-pulse", textClass: "text-warn" },
  failed: { dotClass: "bg-danger", textClass: "text-danger" },
};

type DocumentStatusFields = Pick<
  KnowledgeDocumentSummary,
  "enabled" | "is_indexed" | "is_indexable"
>;

/** 文件狀態的完整文字。停用優先：停用的文件就算還在索引裡，AI 也不會用到。 */
export function documentStatusLabel(doc: DocumentStatusFields): DocumentStatusLabel {
  if (doc.enabled === false) return "已停用";
  if (doc.is_indexed) return "可被搜尋";
  if (doc.is_indexable) return "處理中";
  return "不會被搜尋";
}

const ATTENTION_STATUS: Partial<
  Record<DocumentStatusLabel, { icon: string; className: string }>
> = {
  已停用: { icon: "pause_circle", className: "text-content-subtle" },
  處理中: { icon: "progress_activity", className: "text-warn" },
  不會被搜尋: { icon: "block", className: "text-content-subtle" },
};

/** 正常的文件不顯示東西，樹上一整排綠勾只是噪音；要留意的狀態才寫出來。 */
export default function StatusDot({ doc }: { doc: DocumentStatusFields }) {
  const label = documentStatusLabel(doc);
  const status = ATTENTION_STATUS[label];
  if (!status) return null;

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap text-xs ${status.className}`}
    >
      <span
        aria-hidden="true"
        className={`material-symbols-outlined text-[0.875rem] ${
          label === "處理中" ? "animate-spin" : ""
        }`}
      >
        {status.icon}
      </span>
      {label}
    </span>
  );
}

/** 題庫表格上方顯示目前選中分類的同步狀態；同步失敗時同行寫出說明，不只放 tooltip。 */
export function QaSyncStatusBadge({ status }: { status: QaSyncState }) {
  const label = QA_SYNC_STATUS_LABELS[status];
  const style = QA_SYNC_STATUS_STYLES[status];

  return (
    <span
      role={status === "failed" ? "alert" : "status"}
      className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs"
    >
      <span
        className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap font-medium ${style.textClass}`}
      >
        <span
          aria-hidden="true"
          className={`h-2 w-2 shrink-0 rounded-full ${style.dotClass}`}
        />
        {label}
      </span>
      {status === "failed" && (
        <span className="text-danger">{QA_SYNC_FAILED_HINT}</span>
      )}
    </span>
  );
}

/** 左側分類樹用的小色點：只有 updating 與 failed 才顯示，synced 不加。 */
export function QaSyncStatusDot({ status }: { status: QaSyncState }) {
  if (status === "synced") return null;
  const label = QA_SYNC_STATUS_LABELS[status];
  const style = QA_SYNC_STATUS_STYLES[status];

  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${style.dotClass}`}
    />
  );
}
