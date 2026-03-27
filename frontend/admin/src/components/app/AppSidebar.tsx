import ProjectDropdown from "./ProjectDropdown";
import TabGroup from "./TabGroup";
import { globalTabs, projectTabs, type ProjectSummary, type Tab } from "./navigation";

interface AppSidebarProps {
  active: Tab;
  isPinned: boolean;
  dropdownOpen: boolean;
  projectId: string;
  projects: ProjectSummary[];
  loadingProjects: boolean;
  theme: "light" | "dark";
  onSelectProject: (id: string) => void;
  onSelectTab: (tab: Tab) => void;
  onTogglePin: () => void;
  onDropdownOpenChange: (open: boolean) => void;
  onToggleTheme: () => void;
}

export default function AppSidebar({
  active,
  isPinned,
  dropdownOpen,
  projectId,
  projects,
  loadingProjects,
  theme,
  onSelectProject,
  onSelectTab,
  onTogglePin,
  onDropdownOpenChange,
  onToggleTheme,
}: AppSidebarProps) {
  const isExpanded = isPinned || dropdownOpen;

  return (
    <div
      className={`group/sidebar relative z-20 hidden h-full flex-shrink-0 overflow-hidden transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] md:block ${
        isExpanded ? "w-64" : "w-[72px] hover:w-64"
      }`}
    >
      <aside className="flex h-full w-full flex-col overflow-hidden border-r border-slate-200 bg-white/80 py-5 shadow-[-10px_0_30px_rgba(0,0,0,0.02)_inset] backdrop-blur-xl transition-shadow duration-300 hover:shadow-[10px_0_30px_rgba(0,0,0,0.05)_inset] dark:border-primary/20 dark:bg-background-dark/95 dark:shadow-[-10px_0_30px_rgba(0,0,0,0.5)_inset] dark:hover:shadow-[10px_0_30px_rgba(0,0,0,0.6)_inset]">
        <ProjectDropdown
          projectId={projectId}
          projects={projects}
          loadingProjects={loadingProjects}
          onSelect={onSelectProject}
          isPinned={isExpanded}
          onOpenChange={onDropdownOpenChange}
        />

        <div className="flex-1 flex flex-col w-full px-3 overflow-x-hidden overflow-y-auto no-scrollbar gap-6 mt-4">
          <TabGroup label="Project" tabs={projectTabs} active={active} onSelect={onSelectTab} isPinned={isExpanded} />
          <hr className={`border-slate-200 dark:border-slate-800/60 transition-all duration-300 mx-auto ${isExpanded ? "w-[calc(100%-24px)]" : "w-8 group-hover/sidebar:w-[calc(100%-24px)]"}`} />
          <TabGroup label="Global" tabs={globalTabs} active={active} onSelect={onSelectTab} isPinned={isExpanded} />
        </div>

        <div className="px-3 shrink-0 mt-2 flex items-center gap-1">
          <button
            onClick={onToggleTheme}
            title={theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
            className={`flex-1 flex items-center h-10 px-3 rounded-lg border border-transparent hover:border-slate-200 dark:hover:border-slate-700/50 hover:bg-slate-100 dark:hover:bg-slate-800/40 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition-all duration-300 ${isExpanded ? "justify-start gap-3" : "justify-center"}`}
          >
            <span className="material-symbols-outlined text-[18px]">
              {theme === "dark" ? "light_mode" : "dark_mode"}
            </span>
            <span className={`text-[12.5px] font-medium transition-all duration-300 overflow-hidden whitespace-nowrap ${isExpanded ? "opacity-100 max-w-full" : "opacity-0 max-w-0"}`}>
              {theme === "dark" ? "平常模式" : "深色模式"}
            </span>
          </button>
          <button
            onClick={onTogglePin}
            title={isPinned ? "Unpin Sidebar" : "Pin Sidebar"}
            className={`flex items-center h-10 px-3 rounded-lg border border-transparent hover:border-slate-200 dark:hover:border-slate-700/50 hover:bg-slate-100 dark:hover:bg-slate-800/40 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition-all duration-300 ${isExpanded ? "w-auto" : "w-full justify-center"}`}
          >
            <span className={`material-symbols-outlined text-[18px] transition-transform ${isPinned ? "origin-center rotate-45 select-none" : ""}`}>push_pin</span>
          </button>
        </div>
      </aside>
    </div>
  );
}
