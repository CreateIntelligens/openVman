import {
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import AppSidebar from "./components/app/AppSidebar";
import MascotWidget from "./components/app/MascotWidget";
import OfflineBanner from "./components/app/OfflineBanner";
import TopBar, { MobileNavDrawer } from "./components/app/TopBar";
import {
  buildAdminPath,
  isTab,
  pageComponents,
  parseAdminRoute,
  type AdminRoute,
  type Tab,
} from "./components/app/navigation";
import { BackendHealthProvider } from "./context/BackendHealthContext";
import { MascotProvider } from "./context/MascotContext";
import { NavigationProvider } from "./context/NavigationContext";
import {
  NavigationGuardProvider,
  useNavigationGuard,
} from "./context/NavigationGuardContext";
import { ProjectProvider, useProject } from "./context/ProjectContext";
import { ThemeProvider, useTheme } from "./context/ThemeContext";

function initialRoute(): AdminRoute {
  const route = parseAdminRoute(window.location.pathname, window.location.search);
  if (route) {
    return route;
  }

  const saved = window.localStorage.getItem("brain-active-tab");
  return { tab: isTab(saved) ? saved : "Chat" };
}

function AppContent() {
  const [route, setRoute] = useState<AdminRoute>(initialRoute);
  const [isPinned, setIsPinned] = useState(
    () => window.localStorage.getItem("brain-sidebar-pinned") === "true",
  );
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const {
    projectId,
    setProjectId,
    projects,
    loadingProjects,
    projectError,
    refreshProjects,
  } = useProject();
  const { theme, toggleTheme } = useTheme();
  const { hasUnsavedChanges, requestNavigation } = useNavigationGuard();
  const currentUrlRef = useRef(
    buildAdminPath(route.tab, projectId, route.subView),
  );
  const ActiveComponent = pageComponents[route.tab];

  const applyRoute = useCallback(
    (
      nextRoute: AdminRoute,
      nextProjectId: string,
      historyMode: "push" | "replace" | "none" = "push",
    ) => {
      const path = buildAdminPath(
        nextRoute.tab,
        nextProjectId,
        nextRoute.subView,
      );
      setRoute(nextRoute);
      if (nextProjectId !== projectId) {
        setProjectId(nextProjectId);
      }
      window.localStorage.setItem("brain-active-tab", nextRoute.tab);
      currentUrlRef.current = path;
      if (historyMode === "replace") {
        window.history.replaceState(null, "", path);
      } else if (historyMode === "push") {
        window.history.pushState(null, "", path);
      }
    },
    [projectId, setProjectId],
  );

  useEffect(() => {
    const canonicalPath = buildAdminPath(
      route.tab,
      projectId,
      route.subView,
    );
    currentUrlRef.current = canonicalPath;
    if (`${window.location.pathname}${window.location.search}` !== canonicalPath) {
      window.history.replaceState(null, "", canonicalPath);
    }
  }, [projectId, route]);

  useEffect(() => {
    const handlePopState = () => {
      const targetRoute = parseAdminRoute(
        window.location.pathname,
        window.location.search,
      );
      if (!targetRoute) {
        window.history.replaceState(null, "", currentUrlRef.current);
        return;
      }

      const targetProject =
        new URLSearchParams(window.location.search).get("project") || "default";
      const targetPath = buildAdminPath(
        targetRoute.tab,
        targetProject,
        targetRoute.subView,
      );
      if (!hasUnsavedChanges) {
        applyRoute(targetRoute, targetProject, "none");
        return;
      }

      window.history.pushState(null, "", currentUrlRef.current);
      requestNavigation(() => {
        window.history.pushState(null, "", targetPath);
        applyRoute(targetRoute, targetProject, "none");
      });
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [applyRoute, hasUnsavedChanges, requestNavigation]);

  const switchTab = useCallback(
    (tab: Tab, subView?: string) => {
      if (
        tab === route.tab &&
        (subView === undefined || subView === route.subView)
      ) {
        return;
      }
      requestNavigation(() => applyRoute({ tab, subView }, projectId));
      setMobileNavOpen(false);
    },
    [applyRoute, projectId, requestNavigation, route],
  );

  const switchProject = useCallback(
    (nextProjectId: string) => {
      if (nextProjectId === projectId) {
        return;
      }
      requestNavigation(() => applyRoute(route, nextProjectId));
    },
    [applyRoute, projectId, requestNavigation, route],
  );

  return (
    <NavigationProvider
      currentTab={route.tab}
      currentSubView={route.subView}
      onSelectTab={switchTab}
    >
      <div className="flex h-dvh overflow-hidden bg-surface text-content">
        <AppSidebar
          active={route.tab}
          isPinned={isPinned}
          onSelectTab={switchTab}
          onTogglePin={() =>
            setIsPinned((value) => {
              const next = !value;
              window.localStorage.setItem(
                "brain-sidebar-pinned",
                String(next),
              );
              return next;
            })
          }
        />

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <OfflineBanner />
          <TopBar
            active={route.tab}
            projectId={projectId}
            projects={projects}
            loadingProjects={loadingProjects}
            projectError={projectError}
            theme={theme}
            onSelectProject={switchProject}
            onRetryProjects={() => void refreshProjects()}
            onToggleTheme={toggleTheme}
            onOpenMobileNav={() => setMobileNavOpen(true)}
          />

          <MobileNavDrawer
            open={mobileNavOpen}
            active={route.tab}
            onClose={() => setMobileNavOpen(false)}
            onSelectTab={switchTab}
          />

          <div className="relative min-h-0 flex-1 overflow-hidden">
            <div key={projectId} className="h-full w-full">
              <Suspense
                fallback={
                  <div
                    className="flex h-full items-center justify-center text-sm text-content-muted"
                    role="status"
                  >
                    載入中…
                  </div>
                }
              >
                <ActiveComponent />
              </Suspense>
            </div>
          </div>
        </main>

        <MascotWidget />
      </div>
    </NavigationProvider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <BackendHealthProvider>
        <ProjectProvider>
          <NavigationGuardProvider>
            <MascotProvider>
              <AppContent />
            </MascotProvider>
          </NavigationGuardProvider>
        </ProjectProvider>
      </BackendHealthProvider>
    </ThemeProvider>
  );
}
