import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  fetchProjects,
  type ProjectSummary,
  setActiveProjectId,
} from "../api";
import { errorMessage } from "../utils/errorMessage";
import { readScoped, writeScoped } from "../utils/scopedStorage";

const PROJECT_STORAGE_KEY = "brain-active-project";

interface ProjectContextType {
  projectId: string;
  setProjectId: (id: string) => void;
  projects: ProjectSummary[];
  loadingProjects: boolean;
  projectError: string | null;
  refreshProjects: () => Promise<void>;
}

const ProjectContext = createContext<ProjectContextType | undefined>(undefined);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectIdState] = useState(() => {
    const routeProject = new URLSearchParams(window.location.search).get(
      "project",
    );
    const id =
      routeProject ||
      readScoped(PROJECT_STORAGE_KEY) ||
      "default";
    setActiveProjectId(id);
    return id;
  });
  const projectIdRef = useRef(projectId);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [projectError, setProjectError] = useState<string | null>(null);

  const setProjectId = useCallback((id: string) => {
    projectIdRef.current = id;
    setProjectIdState(id);
    setActiveProjectId(id);
    writeScoped(PROJECT_STORAGE_KEY, id);
  }, []);

  const refreshProjects = useCallback(async () => {
    setLoadingProjects(true);
    setProjectError(null);
    try {
      const response = await fetchProjects();
      setProjects(response.projects);
      const valid = response.projects.some(
        (project) => project.project_id === projectIdRef.current,
      );
      if (!valid && response.projects.length > 0) {
        const fallback =
          response.projects.find((project) => project.project_id === "default")
            ?.project_id ?? response.projects[0].project_id;
        setProjectId(fallback);
      }
    } catch (error) {
      setProjectError(errorMessage(error, "無法載入專案清單，請稍後重試。"));
    } finally {
      setLoadingProjects(false);
    }
  }, [setProjectId]);

  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  return (
    <ProjectContext.Provider
      value={{
        projectId,
        setProjectId,
        projects,
        loadingProjects,
        projectError,
        refreshProjects,
      }}
    >
      {children}
    </ProjectContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useProject() {
  const context = useContext(ProjectContext);
  if (context === undefined) {
    throw new Error("useProject must be used within a ProjectProvider");
  }
  return context;
}
