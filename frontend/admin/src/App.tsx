import { useState } from "react";
import AppSidebar from "./components/app/AppSidebar";
import TopBar, { MobileNavDrawer } from "./components/app/TopBar";
import { allTabs, components, type Tab } from "./components/app/navigation";
import { NavigationProvider } from "./context/NavigationContext";
import { ProjectProvider, useProject } from "./context/ProjectContext";
import { ThemeProvider, useTheme } from "./context/ThemeContext";

function AppContent() {
  const [active, setActive] = useState<Tab>(() => {
    const saved = localStorage.getItem("brain-active-tab");
    return saved && saved in components ? (saved as Tab) : "Chat";
  });
  const [isPinned, setIsPinned] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { projectId, setProjectId, projects, loadingProjects } = useProject();
  const { theme, toggleTheme } = useTheme();

  const switchTab = (tab: Tab) => {
    setActive(tab);
    localStorage.setItem("brain-active-tab", tab);
  };

  return (
    <NavigationProvider onSelectTab={switchTab}>
    <div className="flex h-screen overflow-hidden bg-surface text-content">
      <AppSidebar
        active={active}
        isPinned={isPinned}
        onSelectTab={switchTab}
        onTogglePin={() => setIsPinned((v) => !v)}
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        <TopBar
          active={active}
          projectId={projectId}
          projects={projects}
          loadingProjects={loadingProjects}
          theme={theme}
          onSelectProject={setProjectId}
          onToggleTheme={toggleTheme}
          onOpenMobileNav={() => setMobileNavOpen(true)}
        />

        <MobileNavDrawer
          open={mobileNavOpen}
          active={active}
          onClose={() => setMobileNavOpen(false)}
          onSelectTab={switchTab}
        />

        <div className="relative h-full min-h-0 flex-1 overflow-hidden">
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
    </NavigationProvider>
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
