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
  onSelectProject: (id: string) => void;
  onSelectTab: (tab: Tab) => void;
  onTogglePin: () => void;
  onDropdownOpenChange: (open: boolean) => void;
}

export default function AppSidebar({
  active,
  isPinned,
  dropdownOpen,
  projectId,
  projects,
  loadingProjects,
  onSelectProject,
  onSelectTab,
  onTogglePin,
  onDropdownOpenChange,
}: AppSidebarProps) {
  return (
    <div className={`flex-shrink-0 hidden md:block z-50 relative transition-all duration-300 ${isPinned || dropdownOpen ? "w-64" : "w-[72px]"}`}>
      <aside className={`absolute top-0 left-0 h-full ${isPinned || dropdownOpen ? "w-64" : "w-[72px] hover:w-64"} group/sidebar transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] overflow-hidden bg-background-dark/95 backdrop-blur-xl border-r border-primary/20 shadow-[-10px_0_30px_rgba(0,0,0,0.5)_inset] hover:shadow-[10px_0_30px_rgba(0,0,0,0.6)_inset] flex flex-col py-5 z-50`}>
        <ProjectDropdown
          projectId={projectId}
          projects={projects}
          loadingProjects={loadingProjects}
          onSelect={onSelectProject}
          isPinned={isPinned}
          onOpenChange={onDropdownOpenChange}
        />

        <div className="flex-1 flex flex-col w-full px-3 overflow-x-hidden overflow-y-auto no-scrollbar gap-6 mt-4">
          <TabGroup label="Project" tabs={projectTabs} active={active} onSelect={onSelectTab} isPinned={isPinned} />
          <hr className={`border-slate-800/60 transition-all duration-300 mx-auto ${isPinned ? "w-[calc(100%-24px)]" : "w-8 group-hover/sidebar:w-[calc(100%-24px)]"}`} />
          <TabGroup label="Global" tabs={globalTabs} active={active} onSelect={onSelectTab} isPinned={isPinned} />
        </div>

        <div className="px-3 shrink-0 mt-2">
          <button
            onClick={onTogglePin}
            title={isPinned ? "Unpin Sidebar" : "Pin Sidebar"}
            className={`w-full flex items-center h-10 px-3 rounded-lg border border-transparent hover:border-slate-700/50 hover:bg-slate-800/40 text-slate-400 hover:text-slate-200 transition-all duration-300 ${isPinned ? "justify-end" : "justify-center"}`}
          >
            <span className={`material-symbols-outlined text-[18px] transition-transform ${isPinned ? "origin-center rotate-45 select-none" : ""}`}>push_pin</span>
          </button>
        </div>
      </aside>
    </div>
  );
}
