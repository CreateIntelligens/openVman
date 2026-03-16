import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { fetchProjects, ProjectSummary, setActiveProjectId } from "../api";

const PROJECT_STORAGE_KEY = "brain-active-project";

interface ProjectContextType {
       projectId: string;
       setProjectId: (id: string) => void;
       projects: ProjectSummary[];
       loadingProjects: boolean;
       refreshProjects: () => Promise<void>;
}

const ProjectContext = createContext<ProjectContextType | undefined>(undefined);

export function ProjectProvider({ children }: { children: ReactNode }) {
       const [projectId, setProjectIdState] = useState(() => {
              const id = window.localStorage.getItem(PROJECT_STORAGE_KEY) || "default";
              setActiveProjectId(id);
              return id;
       });
       const [projects, setProjects] = useState<ProjectSummary[]>([]);
       const [loadingProjects, setLoadingProjects] = useState(true);

       const setProjectId = (id: string) => {
              setProjectIdState(id);
              setActiveProjectId(id);
              window.localStorage.setItem(PROJECT_STORAGE_KEY, id);
       };

       const refreshProjects = async () => {
              setLoadingProjects(true);
              try {
                     const response = await fetchProjects();
                     setProjects(response.projects);
                     const valid = response.projects.some((p) => p.project_id === projectId);
                     if (!valid && response.projects.length > 0) {
                            setProjectId("default");
                     }
              } catch {
                     setProjects([]);
              } finally {
                     setLoadingProjects(false);
              }
       };

       useEffect(() => {
              refreshProjects();
              // eslint-disable-next-line react-hooks/exhaustive-deps
       }, [projectId]);

       return (
              <ProjectContext.Provider
                     value={{
                            projectId,
                            setProjectId,
                            projects,
                            loadingProjects,
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
