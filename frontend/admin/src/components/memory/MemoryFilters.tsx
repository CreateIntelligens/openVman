interface MemoryFiltersProps {
  searchTerm: string;
  total: number;
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
    <div className="flex items-center gap-4">
      <div className="relative flex-1">
        <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[1.125rem]">search</span>
        <input
          value={searchTerm}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="篩選記憶..."
          className="w-full pl-9 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950/60 px-4 py-2.5 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
        />
      </div>
      <div className="text-xs text-slate-500">
        共 {total} 筆 · 第 {page}/{totalPages} 頁
      </div>
      <button
        onClick={onRefresh}
        disabled={loading}
        className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:border-primary/40 hover:text-slate-900 dark:hover:text-white transition-colors disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-sm">refresh</span>
        {loading ? "載入中..." : "重新整理"}
      </button>
    </div>
  );
}
