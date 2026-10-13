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

/** 專案層的語音限制；空清單代表「不限制」，實際可用的是帳號授權與這份清單的交集。 */
export interface ProjectPolicyInput {
  allowed_asr_engines: string[];
  default_asr_engine: string | null;
  taiwanese_asr_engine: string | null;
  allowed_tts_voices: string[];
  default_tts_voice: string | null;
}

export interface ProjectPolicy extends ProjectPolicyInput {
  project_id: string;
  updated_by: string | null;
  updated_at: string | null;
}

function projectPolicyPath(projectId: string) {
  return `${projectPath(projectId)}/policy`;
}

export async function fetchProjectPolicy(projectId: string) {
  return fetchJson<ProjectPolicy>(apiUrl(projectPolicyPath(projectId)));
}

export function saveProjectPolicy(projectId: string, policy: ProjectPolicyInput) {
  return jsonRequest<ProjectPolicy>(
    "PUT",
    projectPolicyPath(projectId),
    { ...policy },
  );
}
