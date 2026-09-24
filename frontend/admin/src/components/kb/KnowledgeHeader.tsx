import type { MouseEvent as ReactMouseEvent } from "react";

import LanguageRoutesButton from "./LanguageRoutesButton";

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
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-3 sm:px-4">
      <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
        <button
          type="button"
          onClick={onOpenMobileTree}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-content-subtle hover:bg-surface-sunken hover:text-primary md:hidden"
          aria-label="開啟檔案樹"
          aria-controls="knowledge-tree-panel"
          aria-expanded={mobileTreeOpen}
        >
          <span className="material-symbols-outlined text-[1.125rem]">
            account_tree
          </span>
        </button>
        <span className="material-symbols-outlined text-primary text-[1.5rem]">school</span>
        <h1 className="page-title">知識庫</h1>
        <span className="hidden text-xs text-content-subtle lg:inline">
          {documentCount} 文件 · {indexedCount} 已索引
        </span>
        <div className="ml-auto flex items-center gap-1 rounded-lg border border-border bg-surface-sunken p-0.5 dark:bg-surface-sunken/40 sm:ml-3">
          <button
            onClick={() => setActiveTab("documents")}
            className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
              activeTab === "documents"
                ? "bg-surface-raised text-primary shadow-sm"
                : "text-content-subtle hover:text-content"
            }`}
          >
            文件
          </button>
          <button
            onClick={() => setActiveTab("graph")}
            className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
              activeTab === "graph"
                ? "bg-surface-raised text-primary shadow-sm"
                : "text-content-subtle hover:text-content"
            }`}
          >
            圖譜
          </button>
        </div>
      </div>
      {activeTab === "documents" && (
        <div className="flex w-full items-center justify-end gap-2 sm:w-auto">
          <LanguageRoutesButton projectId={projectId} />
          <button
            onClick={onToggleSourcePanel}
            className="flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/15 transition-colors"
          >
            <span className="material-symbols-outlined text-[1rem]">add</span>
            新增來源
          </button>
          <button
            onClick={onCommit}
            disabled={committing}
            title="採納 raw 區的上傳檔案進知識庫，並重建索引與圖譜"
            className="flex items-center gap-1.5 rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
          >
            <span className={`material-symbols-outlined text-[1rem] ${committing ? "animate-spin" : ""}`}>
              library_add
            </span>
            {committing ? "採納中..." : "採納上傳"}
          </button>
          <button
            onClick={onReindex}
            disabled={reindexing}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            <span className={`material-symbols-outlined text-[1rem] ${reindexing ? "animate-spin" : ""}`}>
              sync
            </span>
            {reindexing ? "索引中..." : "重新索引"}
          </button>
        </div>
      )}
    </div>
  );
}
