import type { PersonaSummary } from "../../api";

interface PersonaCreateFormProps {
  personas: PersonaSummary[];
  newPersonaId: string;
  newPersonaLabel: string;
  templateSourceId: string;
  creatingPersona: boolean;
  cloningPersona: boolean;
  onNewPersonaIdChange: (value: string) => void;
  onNewPersonaLabelChange: (value: string) => void;
  onTemplateSourceIdChange: (value: string) => void;
  onSubmit: () => void;
}

export default function PersonaCreateForm({
  personas,
  newPersonaId,
  newPersonaLabel,
  templateSourceId,
  creatingPersona,
  cloningPersona,
  onNewPersonaIdChange,
  onNewPersonaLabelChange,
  onTemplateSourceIdChange,
  onSubmit,
}: PersonaCreateFormProps) {
  return (
    <div className="rounded-md border border-slate-200 dark:border-slate-800/60 bg-slate-50 dark:bg-slate-900/20 p-4 space-y-4">
      <h3 className="text-[12px] font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">新增角色</h3>
      <div className="space-y-3">
        <input
          value={newPersonaId}
          onChange={(event) => onNewPersonaIdChange(event.target.value)}
          placeholder="ID（例如 support）"
          className="w-full rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/50 px-3 py-2 text-[13px] text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 focus:border-primary/50 focus:outline-none transition-colors"
          title="唯一角色 ID（用於資料夾路徑）"
        />
        <input
          value={newPersonaLabel}
          onChange={(event) => onNewPersonaLabelChange(event.target.value)}
          placeholder="名稱（例如 Support Bot）"
          className="w-full rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/50 px-3 py-2 text-[13px] text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 focus:border-primary/50 focus:outline-none transition-colors"
          title="顯示名稱（僅套用於空白範本）"
        />
        <div className="relative">
          <select
            value={templateSourceId}
            onChange={(event) => onTemplateSourceIdChange(event.target.value)}
            className="select-adaptive w-full text-[13px]"
            title="選擇範本或現有角色複製設定"
          >
            <option value="">── 空白範本 ──</option>
            {personas.map((persona) => (
              <option key={persona.persona_id} value={persona.persona_id}>
                複製自 {persona.persona_id}
              </option>
            ))}
          </select>
          <span className="material-symbols-outlined text-[14px] text-slate-500 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none">expand_more</span>
        </div>
      </div>
      <button
        onClick={onSubmit}
        disabled={creatingPersona || cloningPersona || !newPersonaId.trim()}
        className="w-full rounded-md bg-primary px-3 py-2 text-[13px] font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
      >
        {(creatingPersona || cloningPersona) ? "建立中..." : "建立角色"}
      </button>
    </div>
  );
}
