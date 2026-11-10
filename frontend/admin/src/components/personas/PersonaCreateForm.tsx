import type { PersonaSummary } from "../../api";
import Select from "../Select";

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
  const cloning = Boolean(templateSourceId);
  const canSubmit = cloning || Boolean(newPersonaLabel.trim() || newPersonaId.trim());

  return (
    <div className="rounded-md border border-border bg-surface dark:bg-surface-sunken/20 p-4 space-y-4">
      <h3 className="section-title flex items-center gap-1.5">新增角色</h3>
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="block text-xs font-medium text-content-muted">從哪裡開始</span>
          <Select
            value={templateSourceId}
            onChange={onTemplateSourceIdChange}
            ariaLabel="從哪裡開始"
            options={[
              { value: "", label: "空白角色" },
              ...personas.map((persona) => ({
                value: persona.persona_id,
                label: `複製「${persona.label || persona.persona_id}」`,
              })),
            ]}
            className="w-full text-[0.8125rem]"
          />
        </label>
        {/* 複製時名稱寫在被複製的文件裡，這裡填了也不會生效，不如不讓人填。 */}
        {cloning ? (
          <p className="text-xs leading-5 text-content-muted">
            新角色的名稱會跟原角色一樣。要改名，建立後到「個性與說話方式」改第一行標題。
          </p>
        ) : (
          <label className="block space-y-1">
            <span className="block text-xs font-medium text-content-muted">角色名稱</span>
            <input
              value={newPersonaLabel}
              onChange={(event) => onNewPersonaLabelChange(event.target.value)}
              placeholder="例如 客服小幫手"
              className="input dark:bg-surface-sunken/50 text-[0.8125rem] placeholder:text-content-subtle"
            />
          </label>
        )}
        <label className="block space-y-1">
          <span className="block text-xs font-medium text-content-muted">代號（選填）</span>
          <input
            value={newPersonaId}
            onChange={(event) => onNewPersonaIdChange(event.target.value)}
            placeholder="不填會自動產生"
            className="input dark:bg-surface-sunken/50 text-[0.8125rem] placeholder:text-content-subtle"
          />
        </label>
      </div>
      <button
        onClick={onSubmit}
        disabled={creatingPersona || cloningPersona || !canSubmit}
        className="w-full rounded-md bg-primary px-3 py-2 text-[0.8125rem] font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
      >
        {(creatingPersona || cloningPersona) ? "建立中..." : "建立角色"}
      </button>
    </div>
  );
}
