import { fetchJson, apiUrl, post, jsonRequest, projectPath, PROJECTS_PATH } from "./common";

export interface ProjectSummary {
  project_id: string;
  label: string;
  document_count: number;
  persona_count: number;
}

export interface ProjectsResponse {
  projects: ProjectSummary[];
  project_count: number;
}

export interface ProjectCreateResponse {
  status: string;
  project_id: string;
  label: string;
  project_root: string;
}

export async function fetchProjects() {
  return fetchJson<ProjectsResponse>(apiUrl(PROJECTS_PATH));
}

export async function fetchProjectInfo(projectId: string) {
  return fetchJson<ProjectSummary>(apiUrl(projectPath(projectId)));
}

export function createProject(label: string) {
  return post<ProjectCreateResponse>(PROJECTS_PATH, { label });
}

export function deleteProject(projectId: string) {
  return jsonRequest<{ status: string; project_id: string }>(
    "DELETE",
    PROJECTS_PATH,
    { project_id: projectId },
  );
}
