interface MemoryAddFormProps {
  text: string;
  source: string;
  loading: boolean;
  onTextChange: (value: string) => void;
  onSourceChange: (value: string) => void;
  onSubmit: () => void;
  onReset: () => void;
}

export default function MemoryAddForm({
  text,
  source,
  loading,
  onTextChange,
  onSourceChange,
  onSubmit,
  onReset,
}: MemoryAddFormProps) {
  return (
    <div className="bg-surface dark:bg-surface-sunken/50 rounded-xl border border-border p-6 shadow-sm space-y-6">
      <div className="flex flex-col gap-2">
        <label className="text-sm font-bold text-content-muted" htmlFor="memory-content">
          記憶內容
        </label>
        <textarea
          id="memory-content"
          className="w-full rounded-lg border-border bg-surface-raised text-content focus:ring-2 focus:ring-primary focus:border-primary placeholder:text-content-subtle transition-all p-4 text-base"
          placeholder="描述 Brain 應保留的事實資料或背景脈絡..."
          rows={6}
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
        />
        <p className="text-xs text-content-subtle mt-1">支援純文字格式。</p>
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-sm font-bold text-content-muted" htmlFor="source">
          來源
        </label>
        <div className="relative">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-content-muted text-[1.25rem]">
            person
          </span>
          <input
            id="source"
            className="w-full pl-10 rounded-lg border-border bg-surface-raised text-content focus:ring-2 focus:ring-primary focus:border-primary transition-all h-11"
            value={source}
            onChange={(e) => onSourceChange(e.target.value)}
            placeholder="來源識別標識"
          />
        </div>
      </div>

      <div className="pt-4 flex items-center justify-between gap-4 border-t border-border">
        <button
          onClick={onSubmit}
          disabled={loading || !text.trim()}
          className="flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-white font-bold hover:bg-primary/90 transition-all shadow-lg shadow-primary/20 active:scale-95 disabled:opacity-50"
        >
          <span className="material-symbols-outlined">add_box</span>
          {loading ? "儲存中..." : "新增記憶"}
        </button>
        <button
          onClick={onReset}
          className="text-sm text-content-subtle hover:text-content transition-colors font-medium"
        >
          捨棄變更
        </button>
      </div>
    </div>
  );
}
