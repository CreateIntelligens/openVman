interface MemoryFiltersProps {
  searchTerm: string;
  /** null 代表讀取失敗、筆數未知。 */
  total: number | null;
  page: number;
  totalPages: number;
  loading: boolean;
  onSearchChange: (value: string) => void;
  onRefresh: () => void;
}

export default function MemoryFilters({
  searchTerm,
  total,
  page,
  totalPages,
  loading,
  onSearchChange,
  onRefresh,
}: MemoryFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="relative min-w-0 flex-[1_1_12rem]">
        <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-content-subtle text-[1.125rem]">search</span>
        <input
          value={searchTerm}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="篩選記憶..."
          className="w-full pl-9 rounded-xl border border-border bg-surface-raised dark:bg-surface/60 px-4 py-2.5 text-sm text-content placeholder:text-content-subtle focus:border-primary/50 focus:outline-none"
        />
      </div>
      <div className="whitespace-nowrap text-xs text-content-subtle">
        {total === null ? "筆數未知" : `共 ${total} 筆 · 第 ${page}/${totalPages} 頁`}
      </div>
      <button
        onClick={onRefresh}
        disabled={loading}
        className="flex items-center gap-2 whitespace-nowrap px-4 py-2 rounded-lg border border-border text-content-muted hover:border-primary/40 hover:text-content transition-colors disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-sm">refresh</span>
        {loading ? "載入中..." : "重新整理"}
      </button>
    </div>
  );
}
