import type { SkillInfo } from "../../api";

interface SkillCardProps {
  skill: SkillInfo;
  isEditing: boolean;
  isToggling: boolean;
  onToggle: (skill: SkillInfo) => void;
  onEdit: (skillId: string) => void;
  onDelete: (skill: SkillInfo) => void;
}

export default function SkillCard({
  skill,
  isEditing,
  isToggling,
  onToggle,
  onEdit,
  onDelete,
}: SkillCardProps) {
  return (
    <div className="bg-slate-900/40 border border-primary/10 rounded-xl p-5 transition-transform hover:scale-[1.02]">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <span className="material-symbols-outlined text-primary text-xl">extension</span>
          </div>
          <div>
            <p className="font-bold text-sm">{skill.name}</p>
            <p className="text-[10px] text-slate-500 font-mono">{skill.id} v{skill.version}</p>
          </div>
        </div>

        <button
          onClick={() => onToggle(skill)}
          disabled={isToggling}
          title={skill.enabled ? "停用技能" : "啟用技能"}
          className={`relative w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-50 ${
            skill.enabled ? "bg-emerald-500" : "bg-slate-600"
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-200 ${
              skill.enabled ? "translate-x-5" : "translate-x-0"
            }`}
          />
        </button>
      </div>

      <p className="text-xs text-slate-400 mb-3 line-clamp-2">{skill.description}</p>

      {skill.warnings?.length > 0 && (
        <div className="mb-3 space-y-1">
          {skill.warnings.map((warning, index) => (
            <div key={index} className="flex items-start gap-1.5 px-2.5 py-1.5 bg-amber-500/10 border border-amber-500/20 rounded-lg">
              <span className="material-symbols-outlined text-amber-400 text-[14px] mt-0.5 shrink-0">warning</span>
              <span className="text-[11px] text-amber-300 leading-tight">{warning}</span>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[11px] text-slate-500">
          <span className="material-symbols-outlined text-[14px]">handyman</span>
          {skill.tools.length}個工具
          <span className="text-slate-700 mx-1">|</span>
          <span className="truncate font-mono max-w-[120px]" title={skill.tools.join(", ")}>
            {skill.tools.join(", ")}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => onEdit(skill.id)}
            className={`flex items-center gap-1 px-2 py-1 text-[11px] border rounded-lg transition-colors ${
              isEditing
                ? "text-primary border-primary/30 bg-primary/10"
                : "text-slate-400 hover:text-primary border-slate-700 hover:border-primary/30"
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">edit</span>
            編輯
          </button>
          <button
            onClick={() => onDelete(skill)}
            className="flex items-center gap-1 px-2 py-1 text-[11px] text-slate-400 hover:text-red-400 border border-slate-700 hover:border-red-500/30 rounded-lg transition-colors"
            title="刪除"
          >
            <span className="material-symbols-outlined text-[14px]">delete</span>
          </button>
        </div>
      </div>
    </div>
  );
}
