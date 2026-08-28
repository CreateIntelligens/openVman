import type { MemoryRecord } from "../../api";
import MemoryMetaBadges from "./MemoryMetaBadges";

interface MemoryRecordCardProps {
  memory: MemoryRecord;
  onDelete: (memory: MemoryRecord) => void;
}

export default function MemoryRecordCard({ memory, onDelete }: MemoryRecordCardProps) {
  return (
    <div className="rounded-xl border border-border bg-surface-raised dark:bg-surface/40 p-5 hover:border-border-strong transition-colors">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-7 text-content whitespace-pre-wrap">
            {memory.text}
          </p>
          <div className="mt-3 flex items-center gap-4 text-xs text-content-subtle">
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-[0.875rem]">person</span>
              {memory.source}
            </span>
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-[0.875rem]">calendar_today</span>
              {memory.date}
            </span>
            {memory.metadata && <MemoryMetaBadges metadata={memory.metadata} />}
          </div>
        </div>
        <button
          onClick={() => onDelete(memory)}
          className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/15 transition-colors shrink-0"
        >
          刪除
        </button>
      </div>
    </div>
  );
}
