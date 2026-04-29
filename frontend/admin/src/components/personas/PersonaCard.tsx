import type { PersonaSummary } from "../../api";

interface PersonaCardProps {
  persona: PersonaSummary;
  selected: boolean;
  deleting: boolean;
  onSelect: (persona: PersonaSummary) => void;
  onDelete: (persona: PersonaSummary) => void;
}

export default function PersonaCard({
  persona,
  selected,
  deleting,
  onSelect,
  onDelete,
}: PersonaCardProps) {
  return (
    <div
      className={`rounded-md p-2.5 text-left transition-colors cursor-pointer border ${
        selected
          ? "bg-slate-100 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700 shadow-sm"
          : "bg-transparent border-transparent hover:bg-slate-100 dark:hover:bg-slate-800/30"
      }`}
      onClick={() => onSelect(persona)}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={`font-semibold truncate text-sm ${selected ? "text-primary" : "text-slate-700 dark:text-slate-300"}`}>
          {persona.label || persona.persona_id}
        </span>
        <div className="flex items-center gap-1.5 shrink-0">
          {persona.is_default && (
            <span className="rounded flex items-center bg-amber-500/10 px-1.5 py-0.5 text-[0.5625rem] font-bold uppercase tracking-widest text-amber-500">
              預設
            </span>
          )}
        </div>
      </div>

      <div className="mt-1.5 flex items-center justify-between">
        <span className="text-[0.625rem] font-mono text-slate-500 truncate">{persona.persona_id}</span>
        {selected && !persona.is_default && (
          <button
            onClick={(event) => {
              event.stopPropagation();
              onDelete(persona);
            }}
            disabled={deleting}
            className="flex items-center justify-center rounded bg-red-500/10 px-2 py-0.5 text-[0.625rem] font-bold uppercase tracking-wider text-red-400 hover:bg-red-500 hover:text-white transition-colors disabled:opacity-50"
          >
            {deleting ? "..." : "DEL"}
          </button>
        )}
      </div>
    </div>
  );
}
