import type { MouseEvent as ReactMouseEvent } from "react";

import AccountRowMenu from "../accounts/AccountRowMenu";
import { PageHeader, PageTabs } from "../app/PageHeader";
import LanguageRoutesButton from "./LanguageRoutesButton";

const KNOWLEDGE_TABS = [
  { id: "documents", label: "文件" },
  { id: "graph", label: "圖譜" },
] as const;

interface KnowledgeHeaderProps {
  activeTab: "documents" | "graph";
  setActiveTab: (tab: "documents" | "graph") => void;
  documentCount: number;
  indexedCount: number;
  mobileTreeOpen: boolean;
  onOpenMobileTree: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  onToggleSourcePanel: () => void;
  onCommit: () => void;
  committing: boolean;
  onReindex: () => void;
  reindexing: boolean;
  projectId: string;
}

export default function KnowledgeHeader({
  activeTab,
  setActiveTab,
  documentCount,
  indexedCount,
  mobileTreeOpen,
  onOpenMobileTree,
  onToggleSourcePanel,
  onCommit,
  committing,
  onReindex,
  reindexing,
  projectId,
}: KnowledgeHeaderProps) {
  const tree = (
    <button
      type="button"
      onClick={onOpenMobileTree}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-content-subtle hover:bg-surface-sunken hover:text-primary md:hidden"
      aria-label="開啟檔案樹"
      aria-controls="knowledge-tree-panel"
      aria-expanded={mobileTreeOpen}
    >
      <span className="material-symbols-outlined text-[1.125rem]">account_tree</span>
    </button>
  );

  return (
    <PageHeader
      title="知識庫"
      subtitle={`${documentCount} 文件 · ${indexedCount} 已索引`}
      sticky={false}
      actions={activeTab === "documents" ? (
        <>
          {tree}
          <LanguageRoutesButton projectId={projectId} />
          <button
            onClick={onToggleSourcePanel}
            className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/15 transition-colors"
          >
            <span className="material-symbols-outlined text-[1rem]">add</span>
            新增來源
          </button>
          {/* 低頻的採納與重建索引：寬畫面直接列出，手機收進「更多」，頁首維持一列。 */}
          <div className="hidden items-center gap-2 sm:flex">
            <button
              onClick={onCommit}
              disabled={committing}
              title="採納 raw 區的上傳檔案進知識庫，並重建索引與圖譜"
              className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[1rem] ${committing ? "animate-spin" : ""}`}>
                library_add
              </span>
              {committing ? "採納中..." : "採納上傳"}
            </button>
            <button
              onClick={onReindex}
              disabled={reindexing}
              className="flex items-center gap-1.5 whitespace-nowrap rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[1rem] ${reindexing ? "animate-spin" : ""}`}>
                sync
              </span>
              {reindexing ? "索引中..." : "重新索引"}
            </button>
          </div>
          <div className="sm:hidden">
            <AccountRowMenu
              accountName="知識庫"
              groups={[{
                id: "index",
                label: "索引",
                items: [
                  {
                    id: "commit",
                    label: "採納上傳",
                    onSelect: onCommit,
                    disabledReason: committing ? "採納中…" : undefined,
                  },
                  {
                    id: "reindex",
                    label: "重新索引",
                    onSelect: onReindex,
                    disabledReason: reindexing ? "索引中…" : undefined,
                  },
                ],
              }]}
            />
          </div>
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
  );
}
