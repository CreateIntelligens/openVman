import { getSourceMeta, type SourceType } from "./helpers";

export default function SourceBadge({ sourceType }: { sourceType: SourceType }) {
  const meta = getSourceMeta(sourceType);
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${meta.chipClass}`}
    >
      <span aria-hidden="true" className="material-symbols-outlined text-[0.875rem]">{meta.icon}</span>
      {meta.label}
    </span>
  );
}
