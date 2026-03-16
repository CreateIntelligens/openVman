import { useState, type FC } from "react";
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
        <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center text-white mb-6 shadow-lg shadow-primary/20 shrink-0">
          <span className="material-symbols-outlined text-[24px]">psychology</span>
        </div>

        <div className="flex-1 flex flex-col w-full px-3 overflow-y-auto no-scrollbar gap-6">
          <nav className="flex flex-col gap-3 w-full">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest text-center mb-1">Project</div>
            {projectTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActive(tab.key)}
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

          <hr className="border-slate-800/60 w-8 mx-auto" />

          <nav className="flex flex-col gap-3 w-full">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest text-center mb-1">Global</div>
            {globalTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActive(tab.key)}
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
        </div>

        {/* Global Project Selector at bottom */}
        <div className="mt-4 px-3 w-full shrink-0 relative flex justify-center group" title="Switch Project">
          <div className="w-12 h-12 rounded-xl border border-primary/30 bg-primary/10 flex items-center justify-center text-primary transition-colors group-hover:bg-primary/20 overflow-hidden relative">
            <span className="material-symbols-outlined text-[22px] pointer-events-none z-10">dataset</span>
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              disabled={loadingProjects}
              className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
            >
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id} className="bg-slate-900 text-white font-normal">
                  {p.label || p.project_id}
                </option>
              ))}
              {!projects.length && (
                <option value="default" className="bg-slate-900 text-white font-normal">default</option>
              )}
            </select>
          </div>
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

export default function App() {
  return (
    <ProjectProvider>
      <AppContent />
    </ProjectProvider>
  );
}
