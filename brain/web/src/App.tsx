import { useEffect, useState, type FC } from "react";
import Chat from "./pages/Chat";
import Health from "./pages/Health";
import Embed from "./pages/Embed";
import Search from "./pages/Search";
import Memory from "./pages/Memory";
import Knowledge from "./pages/Knowledge";
import Projects from "./pages/Projects";
import {
  fetchProjects,
  ProjectSummary,
  setActiveProjectId,
} from "./api";

const PROJECT_STORAGE_KEY = "brain-active-project";

const tabs = [
  { key: "Chat", label: "Chat", icon: "chat" },
  { key: "Health", label: "Health", icon: "health_metrics" },
  { key: "Embed", label: "Embed", icon: "code" },
  { key: "Search", label: "Search", icon: "search" },
  { key: "Memory", label: "Memory", icon: "memory" },
  { key: "Knowledge", label: "Workspace", icon: "folder_managed" },
  { key: "Projects", label: "Projects", icon: "folder_copy" },
] as const;

type Tab = (typeof tabs)[number]["key"];

const components: Record<Tab, FC> = { Chat, Health, Embed, Search, Memory, Knowledge, Projects };

/** Sync project id across React state, the api module, and localStorage in one call. */
function persistProject(
  id: string,
  setProjectId: (id: string) => void,
) {
  setProjectId(id);
  setActiveProjectId(id);
  window.localStorage.setItem(PROJECT_STORAGE_KEY, id);
}

export default function App() {
  const [active, setActive] = useState<Tab>("Chat");
  const [projectId, setProjectId] = useState(() => {
    const id = window.localStorage.getItem(PROJECT_STORAGE_KEY) || "default";
    setActiveProjectId(id);
    return id;
  });
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);

  useEffect(() => {
    setLoadingProjects(true);
    fetchProjects()
      .then((response) => {
        setProjects(response.projects);
        const valid = response.projects.some((p) => p.project_id === projectId);
        if (!valid && response.projects.length > 0) {
          persistProject("default", setProjectId);
        }
      })
      .catch(() => {
        setProjects([]);
      })
      .finally(() => setLoadingProjects(false));
  }, [projectId]);

  const ActiveComponent = components[active];

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 border-r border-primary/10 bg-background-dark/50 hidden md:flex flex-col">
        <div className="p-6 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white">
            <span className="material-symbols-outlined text-xl">psychology</span>
          </div>
          <h1 className="text-xl font-bold tracking-tight">Brain</h1>
        </div>

        {/* Project selector */}
        <div className="px-4 mb-4">
          <label className="flex items-center gap-2 w-full rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2.5">
            <span className="material-symbols-outlined text-base text-slate-500">folder_copy</span>
            <select
              value={projectId}
              onChange={(e) => persistProject(e.target.value, setProjectId)}
              disabled={loadingProjects}
              className="flex-1 bg-transparent text-sm text-slate-200 outline-none min-w-0"
            >
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id} className="bg-slate-900">
                  {p.label || p.project_id}
                </option>
              ))}
              {!projects.length && (
                <option value="default" className="bg-slate-900">default</option>
              )}
            </select>
          </label>
        </div>

        <nav className="flex-1 px-4 space-y-2 mt-2">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActive(tab.key)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-colors text-left ${
                active === tab.key
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "hover:bg-slate-800 text-slate-400 border border-transparent"
              }`}
            >
              <span className="material-symbols-outlined">{tab.icon}</span>
              <span className="font-medium">{tab.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <div className="sticky top-0 z-20 border-b border-primary/10 bg-background-dark/90 px-4 py-3 backdrop-blur md:hidden">
          <div className="flex gap-2 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActive(tab.key)}
                className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  active === tab.key
                    ? "bg-primary text-white"
                    : "border border-slate-800 bg-slate-950/50 text-slate-400"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <ActiveComponent key={projectId} />
      </main>
    </div>
  );
}
