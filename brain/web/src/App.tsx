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
  { key: "Personas", label: "Personas", icon: "groups" },
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
  const [isPinned, setIsPinned] = useState(false);
  const { projectId, setProjectId, projects, loadingProjects } = useProject();

  const ActiveComponent = components[active];

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* 1. Icon Sidebar (First Column) */}
      <div className={`flex-shrink-0 hidden md:block z-50 relative transition-all duration-300 ${isPinned ? "w-64" : "w-[72px]"}`}>
        <aside className={`absolute top-0 left-0 h-full ${isPinned ? "w-64" : "w-[72px] hover:w-64"} group/sidebar transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] overflow-hidden bg-background-dark/95 backdrop-blur-xl border-r border-primary/20 shadow-[-10px_0_30px_rgba(0,0,0,0.5)_inset] hover:shadow-[10px_0_30px_rgba(0,0,0,0.6)_inset] flex flex-col py-5 z-50`}>
          {/* Project Selector at top */}
          <ProjectDropdown
            projectId={projectId}
            projects={projects}
            loadingProjects={loadingProjects}
            onSelect={setProjectId}
            isPinned={isPinned}
          />

          <div className="flex-1 flex flex-col w-full px-3 overflow-x-hidden overflow-y-auto no-scrollbar gap-6 mt-4">
            <TabGroup label="Project" tabs={projectTabs} active={active} onSelect={setActive} isPinned={isPinned} />
            <hr className={`border-slate-800/60 transition-all duration-300 mx-auto ${isPinned ? "w-[calc(100%-24px)]" : "w-8 group-hover/sidebar:w-[calc(100%-24px)]"}`} />
            <TabGroup label="Global" tabs={globalTabs} active={active} onSelect={setActive} isPinned={isPinned} />
          </div>

          <div className="px-3 shrink-0 mt-2">
            <button
              onClick={() => setIsPinned(!isPinned)}
              title={isPinned ? "Unpin Sidebar" : "Pin Sidebar"}
              className={`w-full flex items-center h-10 px-3 rounded-lg border border-transparent hover:border-slate-700/50 hover:bg-slate-800/40 text-slate-400 hover:text-slate-200 transition-all duration-300 ${isPinned ? "justify-end" : "justify-center"}`}
            >
              <span className={`material-symbols-outlined text-[18px] transition-transform ${isPinned ? "origin-center rotate-45 select-none" : ""}`}>push_pin</span>
            </button>
          </div>
        </aside>
      </div>

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
  isPinned
}: {
  label: string;
  tabs: readonly { key: Tab; label: string; icon: string }[];
  active: Tab;
  onSelect: (tab: Tab) => void;
  isPinned: boolean;
}) {
  return (
    <nav className="flex flex-col gap-3 w-full">
      <div className={`text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1 transition-all duration-300 w-full whitespace-nowrap overflow-hidden text-ellipsis ${isPinned ? "text-left pl-[13px]" : "text-center group-hover/sidebar:text-left group-hover/sidebar:pl-[13px]"}`}>{label}</div>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onSelect(tab.key)}
          title={tab.label}
          className={`h-12 mx-auto flex items-center rounded-xl transition-all duration-300 shrink-0 overflow-hidden ${isPinned ? "w-full gap-3 pl-[13px]" : "w-12 justify-center group-hover/sidebar:w-full group-hover/sidebar:gap-3 group-hover/sidebar:justify-start group-hover/sidebar:pl-[13px]"} ${active === tab.key
            ? "bg-slate-800/80 text-primary border border-slate-700/50"
            : "hover:bg-slate-800/50 text-slate-400 border border-transparent hover:text-slate-200"
            }`}
        >
          <span className="material-symbols-outlined shrink-0 text-[22px]">
            {tab.icon}
          </span>
          <span className={`font-semibold text-[13.5px] whitespace-nowrap tracking-wide transition-all duration-300 overflow-hidden ${isPinned ? "opacity-100 max-w-full" : "opacity-0 max-w-0 group-hover/sidebar:opacity-100 group-hover/sidebar:max-w-full"}`}>
            {tab.label}
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
  isPinned
}: {
  projectId: string;
  projects: { project_id: string; label: string }[];
  loadingProjects: boolean;
  onSelect: (id: string) => void;
  isPinned: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const activeProject = projects.find((p) => p.project_id === projectId);
  const displayLabel = activeProject?.label || projectId;

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Close dropdown when sidebar collapses (mouse leaves sidebar area)
  useEffect(() => {
    if (!open || isPinned) return;
    const sidebar = ref.current?.closest("aside");
    if (!sidebar) return;
    const handleLeave = () => setOpen(false);
    sidebar.addEventListener("mouseleave", handleLeave);
    return () => sidebar.removeEventListener("mouseleave", handleLeave);
  }, [open, isPinned]);

  return (
    <div ref={ref} className="relative w-full px-3 shrink-0">
      <button
        onClick={() => setOpen(!open)}
        disabled={loadingProjects}
        className={`h-12 mx-auto rounded-xl border border-primary/30 bg-primary/10 flex items-center text-primary transition-all duration-300 hover:bg-primary/20 disabled:opacity-50 overflow-hidden shrink-0 cursor-pointer ${isPinned ? "w-full gap-2.5 pl-[10px] pr-3" : "w-12 justify-center group-hover/sidebar:w-full group-hover/sidebar:gap-2.5 group-hover/sidebar:justify-start group-hover/sidebar:pl-[10px] group-hover/sidebar:pr-3"}`}
        title={`Project: ${displayLabel}`}
      >
        <div className="w-7 h-7 rounded-lg bg-primary/20 flex items-center justify-center shrink-0 shadow-sm border border-primary/30">
          <span className="material-symbols-outlined text-[16px]">dataset</span>
        </div>
        {/* Expanded: project name + unfold icon */}
        <div className={`flex items-center gap-2 min-w-0 flex-1 transition-all duration-300 overflow-hidden ${isPinned ? "opacity-100" : "opacity-0 max-w-0 group-hover/sidebar:opacity-100 group-hover/sidebar:max-w-full"}`}>
          <div className="flex flex-col items-start min-w-0 flex-1">
            <span className="text-[9px] font-bold uppercase tracking-widest text-primary/60 leading-none mb-[2px]">Switch Project</span>
            <span className="text-[13px] font-semibold truncate w-full text-left leading-none text-slate-100">{displayLabel}</span>
          </div>
          <span className="material-symbols-outlined text-[16px] opacity-60 shrink-0">unfold_more</span>
        </div>
      </button>

      {open && (
        <div className="absolute top-full left-3 right-3 mt-2 rounded-xl border border-slate-600 bg-slate-900 shadow-[0_8px_30px_rgba(0,0,0,0.6)] z-[100] overflow-hidden">
          <div className="px-3 py-2.5 border-b border-slate-700/60">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Switch Project</p>
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {projects.map((p) => {
              const isActive = p.project_id === projectId;
              return (
                <button
                  key={p.project_id}
                  onClick={() => { onSelect(p.project_id); setOpen(false); }}
                  className={`w-full text-left px-3 py-2.5 flex items-center gap-3 transition-colors cursor-pointer ${isActive
                    ? "bg-primary/10 text-primary"
                    : "text-slate-300 hover:bg-slate-700/50 hover:text-white"
                    }`}
                >
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center text-[10px] font-bold shrink-0 ${isActive
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
