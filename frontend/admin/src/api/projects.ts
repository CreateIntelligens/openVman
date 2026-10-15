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

/** 專案層的資源與語音限制；空清單代表「不限制」，實際可用的是帳號授權與這份清單的交集。 */
export interface ProjectPolicyInput {
  allowed_asr_engines: string[];
  default_asr_engine: string | null;
  taiwanese_asr_engine: string | null;
  allowed_tts_voices: string[];
  default_tts_voice: string | null;
  allowed_characters?: string[];
  default_character_id?: string | null;
  allowed_backgrounds?: string[];
  default_background_id?: string | null;
  allowed_mascots?: string[];
  default_mascot_id?: string | null;
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

export interface ProjectResourceItem {
  resource_id: string;
  label: string;
  source: "grant" | "project" | "assigned" | "orphan";
  is_default?: boolean;
  assigned_at?: string | null;
  assigned_by?: string | null;
}

export interface ProjectResourcesResponse {
  avatar_character: ProjectResourceItem[];
  avatar_background: ProjectResourceItem[];
  avatar_mascot: ProjectResourceItem[];
  custom_voice: ProjectResourceItem[];
  asr_engine: ProjectResourceItem[];
  defaults: {
    avatar_character: string | null;
    avatar_background: string | null;
    avatar_mascot: string | null;
    custom_voice: string | null;
    asr_engine: string | null;
  };
}

export async function fetchProjectResources(projectId: string) {
  return fetchJson<ProjectResourcesResponse>(apiUrl(`${projectPath(projectId)}/resources`));
}

export function assignProjectResource(projectId: string, resourceType: string, resourceId: string) {
  return jsonRequest<{ status: string; project_id: string; resource_type: string; resource_id: string }>(
    "POST",
    `${projectPath(projectId)}/assignments`,
    { resource_type: resourceType, resource_id: resourceId },
  );
}

export function unassignProjectResource(projectId: string, resourceType: string, resourceId: string) {
  return fetchJson<{ status: string; project_id: string; resource_type: string; resource_id: string }>(
    apiUrl(`${projectPath(projectId)}/assignments/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`),
    { method: "DELETE" },
  );
}
