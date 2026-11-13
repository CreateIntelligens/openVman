import { useState, type MouseEvent as ReactMouseEvent } from "react";

import type { ImportProgress } from "../../hooks/useKnowledgeImport";
import ActionMenu from "../ActionMenu";
import { PageHeader, PageTabs } from "../app/PageHeader";
import ConfirmModal from "../ConfirmModal";
import LanguageRoutesButton from "./LanguageRoutesButton";

const KNOWLEDGE_TABS = [
  { id: "documents", label: "文件" },
  { id: "questions", label: "所有題目" },
  { id: "graph", label: "圖譜" },
] as const;

// 手機要把四顆按鈕排在同一列，內距收小；.btn 不會斷行，字不會被擠成一字一行。
const COMPACT_BUTTON = "max-sm:px-2";

interface KnowledgeHeaderProps {
  activeTab: "documents" | "questions" | "graph";
  setActiveTab: (tab: "documents" | "questions" | "graph") => void;
  documentCount: number;
  /** 第一次載入完之前不知道有幾份，不要先寫出一個錯的數字。 */
  documentsLoaded: boolean;
  processingCount: number;
  mobileTreeOpen: boolean;
  onOpenMobileTree: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  onAddData: () => void;
  importProgress: ImportProgress | null;
  pendingCount: number;
  onImportPending: () => void;
  onReindex: () => void;
  reindexing: boolean;
  onCleanupImages: () => void;
  projectId: string;
}

export default function KnowledgeHeader({
  activeTab,
  setActiveTab,
  documentCount,
  documentsLoaded,
  processingCount,
  mobileTreeOpen,
  onOpenMobileTree,
  onAddData,
  importProgress,
  pendingCount,
  onImportPending,
  onReindex,
  reindexing,
  onCleanupImages,
  projectId,
}: KnowledgeHeaderProps) {
  const [confirmingCleanup, setConfirmingCleanup] = useState(false);

  const maintenanceItems = [
    {
      id: "reindex",
      label: "重建搜尋資料",
      onSelect: onReindex,
      disabledReason: reindexing ? "正在重建，請稍候" : undefined,
    },
    ...(pendingCount > 0
      ? [{
          id: "import-pending",
          label: `匯入等待中的檔案（${pendingCount}）`,
          onSelect: onImportPending,
        }]
      : []),
    {
      id: "cleanup-images",
      label: "清理未使用圖片",
      onSelect: () => setConfirmingCleanup(true),
    },
  ];

  return (
    <>
      <PageHeader
        // 回答語言的面板在手機上相對整個頁首定位。
        className="relative"
        title="知識庫"
        subtitle={(
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {documentsLoaded && (
              <span>
                {documentCount > 0 ? `${documentCount} 份文件` : "還沒有文件"}
                {processingCount > 0 && ` · ${processingCount} 份處理中`}
              </span>
            )}
            {/* 放在標題這一列而不是按鈕列：手機的按鈕列已經排滿，多一顆就會折行。
                觸控裝置的按鈕最小 2.75rem，用負邊界抵掉多出來的高度，出現或消失時才不會推動下面的版面。 */}
            {importProgress && (
              <button
                type="button"
                onClick={onAddData}
                className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary [@media(pointer:coarse)]:-my-3"
              >
                <span aria-hidden="true" className="material-symbols-outlined animate-spin text-[0.875rem]">
                  progress_activity
                </span>
                匯入中 {importProgress.done}/{importProgress.total}
              </button>
            )}
          </span>
        )}
        sticky={false}
        actions={activeTab === "documents" ? (
          <>
            <button
              type="button"
              onClick={onOpenMobileTree}
              className={`btn btn-ghost md:hidden ${COMPACT_BUTTON}`}
              aria-controls="knowledge-tree-panel"
              aria-expanded={mobileTreeOpen}
            >
              目錄
            </button>
            <LanguageRoutesButton projectId={projectId} />
            <ActionMenu
              label="知識庫維護"
              triggerLabel={reindexing ? "重建中…" : "維護"}
              triggerClassName={`btn btn-ghost ${COMPACT_BUTTON}`}
              groups={[{ id: "maintenance", items: maintenanceItems }]}
            />
            <button
              type="button"
              onClick={onAddData}
              className={`btn btn-primary ${COMPACT_BUTTON}`}
            >
              新增資料
            </button>
          </>
        ) : undefined}
        tabs={(
          <PageTabs
            idPrefix="knowledge"
            label="知識庫分頁"
            tabs={KNOWLEDGE_TABS}
            active={activeTab}
            onSelect={setActiveTab}
          />
        )}
      />

      <ConfirmModal
        open={confirmingCleanup}
        title="清理未使用圖片"
        message="整個專案裡，沒有被任何問題用到的圖片都會被刪除，不能復原。確定要清理嗎？"
        confirmLabel="清理"
        danger
        onConfirm={() => {
          setConfirmingCleanup(false);
          onCleanupImages();
        }}
        onCancel={() => setConfirmingCleanup(false)}
      />
    </>
  );
}
