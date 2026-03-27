import { useState } from "react";
import AppSidebar from "./components/app/AppSidebar";
import MobileTopBar from "./components/app/MobileTopBar";
import { allTabs, components, type Tab } from "./components/app/navigation";
import { ProjectProvider, useProject } from "./context/ProjectContext";
import { ThemeProvider, useTheme } from "./context/ThemeContext";

function AppContent() {
  const [active, setActive] = useState<Tab>(() => {
    const saved = localStorage.getItem("brain-active-tab");
    return saved && saved in components ? (saved as Tab) : "Chat";
  });
  const [isPinned, setIsPinned] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const { projectId, setProjectId, projects, loadingProjects } = useProject();
  const { theme, toggleTheme } = useTheme();

  const switchTab = (tab: Tab) => {
    setActive(tab);
    localStorage.setItem("brain-active-tab", tab);
  };

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 dark:bg-background-dark">
      <AppSidebar
        active={active}
        isPinned={isPinned}
        dropdownOpen={dropdownOpen}
        projectId={projectId}
        projects={projects}
        loadingProjects={loadingProjects}
        theme={theme}
        onSelectProject={setProjectId}
        onSelectTab={switchTab}
        onTogglePin={() => setIsPinned((current) => !current)}
        onDropdownOpenChange={setDropdownOpen}
        onToggleTheme={toggleTheme}
      />

      <main className="flex-1 flex flex-col overflow-hidden bg-slate-50 dark:bg-background-dark">
        <MobileTopBar
          active={active}
          projectId={projectId}
          projects={projects}
          loadingProjects={loadingProjects}
          onSelectProject={setProjectId}
          onSelectTab={switchTab}
        />

        <div className="flex-1 h-full min-h-0 overflow-hidden relative">
          {allTabs.map((tab) => {
            const Component = components[tab.key];
            return (
              <div
                key={`${tab.key}-${projectId}`}
                className={`h-full w-full ${active === tab.key ? "" : "hidden"}`}
              >
                <Component />
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <ProjectProvider>
        <AppContent />
      </ProjectProvider>
    </ThemeProvider>
  );
}
