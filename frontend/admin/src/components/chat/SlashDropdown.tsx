import type { SkillInfo } from "../../api";

interface SlashDropdownProps {
  matches: SkillInfo[];
  selectedIndex: number;
  onPick: (skill: SkillInfo) => void;
}

const SCOPE_BADGE: Record<NonNullable<SkillInfo["scope"]>, string> = {
  project: "rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary",
  shared: "rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] font-medium text-content-muted",
};

function ScopeBadge({ scope }: { scope?: SkillInfo["scope"] }) {
  if (!scope) return null;
  return <span className={SCOPE_BADGE[scope]}>{scope}</span>;
}

export const SlashDropdown: React.FC<SlashDropdownProps> = ({ matches, selectedIndex, onPick }) => {
  if (matches.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-1 z-30 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-2xl overflow-hidden max-h-[240px] overflow-y-auto">
      {matches.map((skill, i) => (
        <button
          key={skill.id}
          onMouseDown={(e) => {
            e.preventDefault();
            onPick(skill);
          }}
          className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
            i === selectedIndex
              ? "bg-primary/20 text-slate-900 dark:text-white"
              : "text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
          }`}
        >
          <span className="material-symbols-outlined text-primary text-lg">extension</span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold font-mono">/{skill.id}</span>
              <span className="text-[11px] text-content-muted">{skill.name}</span>
              <ScopeBadge scope={skill.scope} />
            </div>
            <div className="text-[11px] text-slate-500 truncate">
              {skill.description || skill.name}
            </div>
          </div>
        </button>
      ))}
    </div>
  );
};
