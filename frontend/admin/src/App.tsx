import { useState } from "react";
import AppSidebar from "./components/app/AppSidebar";
import OfflineBanner from "./components/app/OfflineBanner";
import TopBar, { MobileNavDrawer } from "./components/app/TopBar";
import { allTabs, components, type Tab } from "./components/app/navigation";
import { BackendHealthProvider, useBackendHealth } from "./context/BackendHealthContext";
import { NavigationProvider } from "./context/NavigationContext";
import { ProjectProvider, useProject } from "./context/ProjectContext";
import { ThemeProvider, useTheme } from "./context/ThemeContext";

function AppContent() {
  const [active, setActive] = useState<Tab>(() => {
    const saved = localStorage.getItem("brain-active-tab");
    return saved && saved in components ? (saved as Tab) : "Chat";
  });
  const [isPinned, setIsPinned] = useState(() => localStorage.getItem("brain-sidebar-pinned") === "true");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { projectId, setProjectId, projects, loadingProjects } = useProject();
  const { theme, toggleTheme } = useTheme();
  const { recoveryCounter } = useBackendHealth();

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
        onTogglePin={() => setIsPinned((v) => {
          const next = !v;
          localStorage.setItem("brain-sidebar-pinned", String(next));
          return next;
        })}
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        <OfflineBanner />
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
            const isActive = active === tab.key;
            const remountKey = isActive
              ? `${tab.key}-${projectId}`
              : `${tab.key}-${projectId}-${recoveryCounter}`;
            return (
              <div
                key={remountKey}
                className={`h-full w-full ${isActive ? "" : "hidden"}`}
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
      <BackendHealthProvider>
        <ProjectProvider>
          <AppContent />
        </ProjectProvider>
      </BackendHealthProvider>
    </ThemeProvider>
  );
}
