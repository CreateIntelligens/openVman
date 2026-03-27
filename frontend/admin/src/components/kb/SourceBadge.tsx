import { getSourceMeta, type SourceMode } from "./helpers";

export default function SourceBadge({ sourceType }: { sourceType: SourceMode }) {
  const meta = getSourceMeta(sourceType);
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${meta.chipClass}`}>
      <span className="material-symbols-outlined text-[12px]">{meta.icon}</span>
      {meta.label}
    </span>
  );
}
