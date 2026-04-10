import { allTabs, type ProjectSummary, type Tab } from "./navigation";
import Select from "../Select";

interface MobileTopBarProps {
  active: Tab;
  projectId: string;
  projects: ProjectSummary[];
  loadingProjects: boolean;
  onSelectProject: (id: string) => void;
  onSelectTab: (tab: Tab) => void;
}

export default function MobileTopBar({
  active,
  projectId,
  projects,
  loadingProjects,
  onSelectProject,
  onSelectTab,
}: MobileTopBarProps) {
  return (
    <div className="sticky top-0 z-20 border-b border-primary/10 bg-white/90 dark:bg-background-dark/90 px-4 py-3 backdrop-blur md:hidden flex flex-col gap-3">
      <div className="flex items-center gap-2 w-full rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
        <span className="material-symbols-outlined text-sm text-primary">dataset</span>
        <Select
          value={projectId}
          onChange={onSelectProject}
          disabled={loadingProjects}
          options={
            projects.length
              ? projects.map((project) => ({
                  value: project.project_id,
                  label: project.label || project.project_id,
                }))
              : [{ value: "default", label: "default" }]
          }
          className="flex-1 text-xs min-w-0"
        />
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
        {allTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onSelectTab(tab.key)}
            className={`whitespace-nowrap flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-colors ${active === tab.key ? "bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white border border-slate-200 dark:border-slate-700" : "border border-slate-200 dark:border-slate-800/50 bg-white dark:bg-slate-950/30 text-slate-500 dark:text-slate-400"}`}
          >
            <span className={`material-symbols-outlined text-[16px] ${active === tab.key ? "text-primary" : ""}`}>
              {tab.icon}
            </span>
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  );
}
