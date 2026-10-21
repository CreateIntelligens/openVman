import type { MouseEvent as ReactMouseEvent } from "react";

import ActionMenu from "../ActionMenu";
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

  const indexActions = [
    {
      id: "commit",
      label: "採納上傳",
      busyLabel: "採納中…",
      busy: committing,
      onSelect: onCommit,
      icon: "library_add",
      title: "採納 raw 區的上傳檔案進知識庫，並重建索引與圖譜",
      className: "border border-primary text-primary hover:bg-primary/10",
    },
    {
      id: "reindex",
      label: "重新索引",
      busyLabel: "索引中…",
      busy: reindexing,
      onSelect: onReindex,
      icon: "sync",
      title: undefined,
      className: "bg-primary text-white hover:bg-primary/90",
    },
  ];

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
            {indexActions.map((action) => (
              <button
                key={action.id}
                onClick={action.onSelect}
                disabled={action.busy}
                title={action.title}
                className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-bold transition-colors disabled:opacity-50 ${action.className}`}
              >
                <span className={`material-symbols-outlined text-[1rem] ${action.busy ? "animate-spin" : ""}`}>
                  {action.icon}
                </span>
                {action.busy ? action.busyLabel : action.label}
              </button>
            ))}
          </div>
          <div className="sm:hidden">
            <ActionMenu
              label="知識庫"
              groups={[{
                id: "index",
                label: "索引",
                items: indexActions.map((action) => ({
                  id: action.id,
                  label: action.label,
                  onSelect: action.onSelect,
                  disabledReason: action.busy ? action.busyLabel : undefined,
                })),
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
