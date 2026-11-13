import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";

import type { KnowledgeDocumentSummary, KnowledgeNoteFormat } from "../../api";
import { isImportItemActive, type KnowledgeImport } from "../../hooks/useKnowledgeImport";
import type { QaNode } from "../../hooks/useQaNodes";
import ConfirmModal from "../ConfirmModal";
import { formatSize, KNOWLEDGE_LANGUAGE_LABELS } from "./helpers";
import ImportResultList, { ImportFileName } from "./ImportResultList";
import SourcePanel from "./SourcePanel";
import { documentStatusLabel, type DocumentStatusLabel } from "./StatusDot";

const STATUS_ORDER: DocumentStatusLabel[] = ["可被搜尋", "處理中", "已停用", "不會被搜尋"];

export interface KnowledgeSummary {
  documentCount: number;
  statuses: { label: DocumentStatusLabel; count: number }[];
  languages: { label: string; count: number }[];
  categoryCount: number;
  questionCount: number;
}

/** 一個分類可以掛在好幾個上層，同一個分類不重複算。 */
function collectQaNodes(nodes: QaNode[], seen = new Map<string, QaNode>()): Map<string, QaNode> {
  for (const node of nodes) {
    if (!seen.has(node.node_id)) {
      seen.set(node.node_id, node);
      collectQaNodes(node.children ?? [], seen);
    }
  }
  return seen;
}

export function summarizeKnowledge(
  documents: KnowledgeDocumentSummary[],
  nodesTree: QaNode[],
): KnowledgeSummary {
  const statusCounts = new Map<DocumentStatusLabel, number>();
  const languageCounts = new Map<string, number>();
  for (const document of documents) {
    const status = documentStatusLabel(document);
    statusCounts.set(status, (statusCounts.get(status) ?? 0) + 1);
    const language = document.language ? KNOWLEDGE_LANGUAGE_LABELS[document.language] : undefined;
    if (language) languageCounts.set(language, (languageCounts.get(language) ?? 0) + 1);
  }
  const categories = [...collectQaNodes(nodesTree).values()];
  return {
    documentCount: documents.length,
    statuses: STATUS_ORDER
      .filter((label) => statusCounts.has(label))
      .map((label) => ({ label, count: statusCounts.get(label) as number })),
    languages: [...languageCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, count]) => ({ label, count })),
    categoryCount: categories.length,
    questionCount: categories.reduce((sum, node) => sum + (node.qa_entries?.length ?? 0), 0),
  };
}

function KnowledgeStatus({ summary }: { summary: KnowledgeSummary }) {
  const rows: { label: string; value: string }[] = [];
  if (summary.documentCount > 0) {
    rows.push({
      label: "文件",
      value: [
        `${summary.documentCount} 份`,
        ...summary.statuses.map(({ label, count }) => `${label} ${count}`),
      ].join("、"),
    });
  }
  if (summary.languages.length > 0) {
    rows.push({
      label: "語言",
      value: summary.languages.map(({ label, count }) => `${label} ${count}`).join("、"),
    });
  }
  if (summary.categoryCount > 0) {
    rows.push({
      label: "快速問答",
      value: `${summary.categoryCount} 個分類、${summary.questionCount} 題`,
    });
  }
  return (
    <dl className="space-y-1 text-sm">
      {rows.map(({ label, value }) => (
        <div key={label} className="flex gap-3">
          <dt className="w-[5rem] shrink-0 text-content-muted">{label}</dt>
          <dd className="min-w-0 break-words text-content">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

interface KnowledgeHomeProps {
  importer: KnowledgeImport;
  documents: KnowledgeDocumentSummary[];
  /** 文件清單第一次載入完之前，不能下「知識庫是空的」的結論。 */
  documentsLoaded: boolean;
  nodesTree: QaNode[];
  maxUploadLabel: string;
  crawlUrlValue: string;
  setCrawlUrlValue: (value: string) => void;
  crawling: boolean;
  onCrawl: () => void;
  onOpenComposer: (format: KnowledgeNoteFormat) => void;
  onViewDocument: (path: string) => void;
  onViewQaNode: (nodeId: string) => void;
  onRenameQaNode: (nodeId: string) => void;
  onOpenMobileTree: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  /** 這個帳號能不能用「AI 整理排版」。 */
  allowAiCleanup?: boolean;
}

/** 右側的「新增資料」畫面：沒有選任何文件時顯示，頁首的「新增資料」也回到這裡。 */
export default function KnowledgeHome({
  importer,
  allowAiCleanup = true,
  documents,
  documentsLoaded,
  nodesTree,
  maxUploadLabel,
  crawlUrlValue,
  setCrawlUrlValue,
  crawling,
  onCrawl,
  onOpenComposer,
  onViewDocument,
  onViewQaNode,
  onRenameQaNode,
  onOpenMobileTree,
}: KnowledgeHomeProps) {
  const { items, pendingFiles } = importer;
  const [discardTarget, setDiscardTarget] = useState<string | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // 正在匯入時才打開這個畫面（拖檔案進來、按頁首的「匯入中」），也算有新東西要看。
  const previousItemCount = useRef(items.some(isImportItemActive) ? 0 : items.length);

  // 結果在上傳區下面，窄畫面一開始看不到；有新檔案進來就捲過去，只換狀態時不動。
  useEffect(() => {
    if (items.length > previousItemCount.current) {
      resultsRef.current?.scrollIntoView?.({ block: "nearest" });
    }
    previousItemCount.current = items.length;
  }, [items.length]);

  const summary = summarizeKnowledge(documents, nodesTree);
  const isEmpty = documentsLoaded && documents.length === 0 && nodesTree.length === 0;
  const showStatus = documentsLoaded && !isEmpty;

  return (
    <main className="min-w-0 flex-1 overflow-y-auto">
      {/* 底部多留空間：捲到最後，最下面的內容才不會被小助理蓋住。 */}
      <div className="mx-auto w-full max-w-[48rem] space-y-6 p-4 pb-24 md:p-6 md:pb-24">
        <div>
          <h2 className="page-section-title">新增資料</h2>
          {isEmpty && (
            <p className="mt-1 text-sm text-content-muted">
              知識庫還沒有資料。先把手上的文件或問答表放進來，AI 才有東西可以回答。
            </p>
          )}
        </div>

        <SourcePanel
          onPickFiles={importer.startFiles}
          maxUploadLabel={maxUploadLabel}
          targetDir={importer.targetDir}
          targetOptions={importer.targetOptions}
          onTargetDirChange={importer.setTargetDir}
          skipNormalize={importer.skipNormalize}
          onSkipNormalizeChange={importer.setSkipNormalize}
          fileInputRef={fileInputRef}
          crawlUrlValue={crawlUrlValue}
          setCrawlUrlValue={setCrawlUrlValue}
          crawling={crawling}
          onCrawl={onCrawl}
          onOpenComposer={onOpenComposer}
          prominent={isEmpty}
          allowAiCleanup={allowAiCleanup}
        />

        <div ref={resultsRef}>
          <ImportResultList
            items={items}
            nodesTree={nodesTree}
            onViewDocument={onViewDocument}
            onViewQaNode={onViewQaNode}
            onRenameQaNode={onRenameQaNode}
            onRetry={importer.retryItem}
            onPickAgain={() => fileInputRef.current?.click()}
            onClear={importer.clearResults}
          />
        </div>

        {pendingFiles.length > 0 && (
          <section aria-labelledby="knowledge-pending-files" className="rounded-xl border border-border bg-surface-raised px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
              <h3 id="knowledge-pending-files" className="min-w-0 text-sm font-semibold text-content">
                有 {pendingFiles.length} 個之前上傳、還沒匯入的檔案
              </h3>
              <button
                type="button"
                className="btn btn-ghost px-2.5 py-1 text-xs"
                onClick={importer.importPending}
              >
                全部匯入
              </button>
            </div>
            <ul className="mt-1 divide-y divide-border">
              {pendingFiles.map((file) => (
                <li key={file.path} className="flex items-center justify-between gap-3 py-2">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <ImportFileName name={file.path} />
                    <span className="shrink-0 text-xs text-content-subtle">{formatSize(file.size)}</span>
                  </span>
                  <button
                    type="button"
                    className="btn btn-danger shrink-0 px-2.5 py-1 text-xs"
                    aria-label={`移除 ${file.path}`}
                    onClick={() => setDiscardTarget(file.path)}
                  >
                    移除
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {showStatus && (
          <section aria-labelledby="knowledge-status" className="space-y-2">
            <h3 id="knowledge-status" className="text-sm font-semibold text-content">現況</h3>
            <KnowledgeStatus summary={summary} />
            <button type="button" className="btn btn-ghost md:hidden" onClick={onOpenMobileTree}>
              查看文件與快速問答
            </button>
          </section>
        )}
      </div>

      <ConfirmModal
        open={discardTarget !== null}
        title="移除這個檔案？"
        message={`「${discardTarget ?? ""}」還沒匯入，移除後檔案會被刪除，不能復原。`}
        confirmLabel="移除"
        danger
        onConfirm={() => {
          if (discardTarget) void importer.discardPending(discardTarget);
          setDiscardTarget(null);
        }}
        onCancel={() => setDiscardTarget(null)}
      />
    </main>
  );
}
