import type { ToolInfo } from "../../api";
import { getSkillIdFromToolName } from "./helpers";

interface ToolTableProps {
  tools: ToolInfo[];
  resolveSkillName?: (skillId: string) => string | undefined;
}

export default function ToolTable({ tools, resolveSkillName }: ToolTableProps) {
  const showSkillColumn = Boolean(resolveSkillName);

  return (
    <div className="bg-white dark:bg-slate-900/40 border border-slate-200 dark:border-primary/10 rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-widest text-slate-500 border-b border-slate-200 dark:border-slate-800">
              <th className="px-6 py-3">名稱</th>
              <th className="px-6 py-3">說明</th>
              {showSkillColumn && <th className="px-6 py-3">技能</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800/60">
            {tools.map((tool) => {
              const skillId = showSkillColumn ? getSkillIdFromToolName(tool.name) : "";
              const skillName = skillId && resolveSkillName ? resolveSkillName(skillId) ?? skillId : "";

              return (
                <tr key={tool.name} className="text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors">
                  <td className="px-6 py-3 font-mono text-xs whitespace-nowrap">{tool.name}</td>
                  <td className="px-6 py-3 text-xs text-slate-500 dark:text-slate-400 max-w-md truncate" title={tool.description}>
                    {tool.description}
                  </td>
                  {showSkillColumn && (
                    <td className="px-6 py-3 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-primary/10 text-primary border border-primary/20">
                        <span className="material-symbols-outlined text-[12px]">extension</span>
                        {skillName}
                      </span>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
