import { useState, type FC } from "react";
import Chat from "./pages/Chat";
import Health from "./pages/Health";
import Embed from "./pages/Embed";
import Search from "./pages/Search";
import Memory from "./pages/Memory";
import Knowledge from "./pages/Knowledge";

const tabs = [
  { key: "Chat", label: "Chat", icon: "chat" },
  { key: "Health", label: "Health", icon: "health_metrics" },
  { key: "Embed", label: "Embed", icon: "code" },
  { key: "Search", label: "Search", icon: "search" },
  { key: "Memory", label: "Memory", icon: "memory" },
  { key: "Knowledge", label: "Workspace", icon: "folder_managed" },
] as const;

type Tab = (typeof tabs)[number]["key"];

const components: Record<Tab, FC> = { Chat, Health, Embed, Search, Memory, Knowledge };

export default function App() {
  const [active, setActive] = useState<Tab>("Chat");
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

        <nav className="flex-1 px-4 space-y-2 mt-4">
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
        <ActiveComponent />
      </main>
    </div>
  );
}
