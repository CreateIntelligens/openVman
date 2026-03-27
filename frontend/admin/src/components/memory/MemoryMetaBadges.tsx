import { parseMetadataJson } from "./helpers";

interface MemoryMetaBadgesProps {
  metadata: string;
}

export default function MemoryMetaBadges({ metadata }: MemoryMetaBadgesProps) {
  const meta = parseMetadataJson(metadata);

  return (
    <>
      {meta.persona_id && meta.persona_id !== "default" && (
        <span className="flex items-center gap-1 font-semibold text-primary/80 uppercase text-[10px] bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
          <span className="material-symbols-outlined text-[12px]">masks</span>
          {meta.persona_id}
        </span>
      )}
      {meta.source_type && (
        <span className="rounded bg-white dark:bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 dark:text-slate-400">
          {meta.source_type}
        </span>
      )}
      {meta.turn && (
        <span className="rounded bg-white dark:bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 dark:text-slate-400">
          turn {meta.turn}
        </span>
      )}
    </>
  );
}
