import { useEffect, useRef, useState, type FC } from "react";
import Chat from "./pages/Chat";
import Health from "./pages/Health";
import Embed from "./pages/Embed";
import Search from "./pages/Search";
import Memory from "./pages/Memory";
import Knowledge from "./pages/Knowledge";
import Projects from "./pages/Projects";
import Personas from "./pages/Personas";
import { ProjectProvider, useProject } from "./context/ProjectContext";

const projectTabs = [
  { key: "Chat", label: "Chat", icon: "chat" },
  { key: "Personas", label: "Personas", icon: "styles" },
  { key: "Knowledge", label: "Workspace", icon: "folder_managed" },
  { key: "Memory", label: "Memory", icon: "memory" },
  { key: "Search", label: "Search", icon: "search" },
] as const;

const globalTabs = [
  { key: "Projects", label: "Projects", icon: "folder_copy" },
  { key: "Health", label: "Health", icon: "health_metrics" },
  { key: "Embed", label: "Embed", icon: "code" },
] as const;

const allTabs = [...projectTabs, ...globalTabs] as const;

type Tab = (typeof allTabs)[number]["key"];

const components: Record<Tab, FC> = { Chat, Health, Embed, Search, Memory, Personas, Knowledge, Projects };

function AppContent() {
  const [active, setActive] = useState<Tab>("Chat");
  const { projectId, setProjectId, projects, loadingProjects } = useProject();

  const ActiveComponent = components[active];

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* 1. Icon Sidebar (First Column) */}
      <aside className="w-[72px] flex-shrink-0 border-r border-primary/10 bg-background-dark/80 flex flex-col items-center py-5 hidden md:flex z-50">
        {/* Project Selector at top */}
        <ProjectDropdown
          projectId={projectId}
          projects={projects}
          loadingProjects={loadingProjects}
          onSelect={setProjectId}
        />

        <div className="flex-1 flex flex-col w-full px-3 overflow-y-auto no-scrollbar gap-6 mt-4">
          <TabGroup label="Project" tabs={projectTabs} active={active} onSelect={setActive} />
          <hr className="border-slate-800/60 w-8 mx-auto" />
          <TabGroup label="Global" tabs={globalTabs} active={active} onSelect={setActive} />
        </div>
      </aside>

      {/* Main Container for Contextual Sidebar + Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden bg-background">
        {/* Mobile Top Bar */}
        <div className="sticky top-0 z-20 border-b border-primary/10 bg-background-dark/90 px-4 py-3 backdrop-blur md:hidden flex flex-col gap-3">
          <div className="flex items-center gap-2 w-full rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
            <span className="material-symbols-outlined text-sm text-primary">dataset</span>
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              disabled={loadingProjects}
              className="flex-1 bg-transparent text-xs font-bold text-white outline-none min-w-0"
            >
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id} className="bg-slate-900 font-normal">
                  {p.label || p.project_id}
                </option>
              ))}
              {!projects.length && (
                <option value="default" className="bg-slate-900 font-normal">default</option>
              )}
            </select>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
            {allTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActive(tab.key)}
                className={`whitespace-nowrap flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-colors ${active === tab.key
                  ? "bg-slate-800 text-white border border-slate-700"
                  : "border border-slate-800/50 bg-slate-950/30 text-slate-400"
                  }`}
              >
                <span className={`material-symbols-outlined text-[16px] ${active === tab.key ? "text-primary" : ""}`}>
                  {tab.icon}
                </span>
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* 2. Contextual Sidebar & 3. Main Content Wrapper */}
        <div className="flex-1 h-full min-h-0 overflow-hidden relative">
          <ActiveComponent key={`${active}-${projectId}`} />
        </div>
      </main>
    </div>
  );
}

function TabGroup({
  label,
  tabs,
  active,
  onSelect,
}: {
  label: string;
  tabs: readonly { key: Tab; label: string; icon: string }[];
  active: Tab;
  onSelect: (tab: Tab) => void;
}) {
  return (
    <nav className="flex flex-col gap-3 w-full">
      <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest text-center mb-1">{label}</div>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onSelect(tab.key)}
          title={tab.label}
          className={`w-12 h-12 mx-auto flex items-center justify-center rounded-xl transition-all group relative ${active === tab.key
              ? "bg-slate-800/80 text-primary border border-slate-700/50 shadow-inner"
              : "hover:bg-slate-800/50 text-slate-400 border border-transparent hover:text-slate-200"
            }`}
        >
          <span className={`material-symbols-outlined text-[22px] transition-transform ${active === tab.key ? "scale-110" : "group-hover:scale-110"}`}>
            {tab.icon}
          </span>
        </button>
      ))}
    </nav>
  );
}

function ProjectDropdown({
  projectId,
  projects,
  loadingProjects,
  onSelect,
}: {
  projectId: string;
  projects: { project_id: string; label: string }[];
  loadingProjects: boolean;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const activeProject = projects.find((p) => p.project_id === projectId);
  const displayLabel = activeProject?.label || projectId;
  const initials = displayLabel.slice(0, 2).toUpperCase();

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div ref={ref} className="relative px-3 w-full shrink-0">
      <button
        onClick={() => setOpen(!open)}
        disabled={loadingProjects}
        className="w-12 h-12 mx-auto rounded-xl border border-primary/30 bg-primary/10 flex flex-col items-center justify-center text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
        title={`Project: ${displayLabel}`}
      >
        <span className="text-[11px] font-black leading-none tracking-tight">{initials}</span>
        <span className="material-symbols-outlined text-[10px] mt-0.5 opacity-60">expand_more</span>
      </button>

      {open && (
        <div className="absolute top-full left-3 mt-2 w-56 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl z-[100] overflow-hidden">
          <div className="px-3 py-2.5 border-b border-slate-800">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Switch Project</p>
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {projects.map((p) => {
              const isActive = p.project_id === projectId;
              return (
                <button
                  key={p.project_id}
                  onClick={() => { onSelect(p.project_id); setOpen(false); }}
                  className={`w-full text-left px-3 py-2.5 flex items-center gap-3 transition-colors ${
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
                  }`}
                >
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center text-[10px] font-bold shrink-0 ${
                    isActive
                      ? "bg-primary/20 text-primary border border-primary/30"
                      : "bg-slate-800 text-slate-400 border border-slate-700"
                  }`}>
                    {(p.label || p.project_id).slice(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold truncate">{p.label || p.project_id}</p>
                    <p className="text-[10px] text-slate-500 font-mono truncate">{p.project_id}</p>
                  </div>
                  {isActive && (
                    <span className="material-symbols-outlined text-primary text-[16px] shrink-0">check</span>
                  )}
                </button>
              );
            })}
            {!projects.length && (
              <p className="px-3 py-4 text-xs text-slate-500 text-center">No projects</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <ProjectProvider>
      <AppContent />
    </ProjectProvider>
  );
}
