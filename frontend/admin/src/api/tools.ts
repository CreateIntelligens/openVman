import {
  apiUrl,
  fetchJson,
  post,
  projectUrl,
  request,
  skillPath,
  type QueryParams,
  SKILLS_PATH,
  TOOLS_PATH,
} from "./common";

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  version: string;
  scope?: "shared" | "project";
  project_id?: string | null;
  enabled: boolean;
  tools: string[];
  warnings: string[];
}

export interface SkillScope {
  scope?: "shared" | "project";
  project_id?: string;
}

function scopeParams(scope?: SkillScope): QueryParams {
  if (!scope?.scope) return {};
  const params: QueryParams = { scope: scope.scope };
  if (scope.project_id) params.project_id = scope.project_id;
  return params;
}

export function skillKey(skill: { id: string; scope?: SkillScope["scope"]; project_id?: string | null }): string {
  return skill.scope === "project"
    ? `project:${skill.project_id ?? "default"}:${skill.id}`
    : `shared:${skill.id}`;
}

export interface ToolsData {
  tools: ToolInfo[];
  skill_tools: ToolInfo[];
  skills: SkillInfo[];
}

export interface SkillToggleResponse {
  status: string;
  skill_id: string;
  scope: "shared" | "project";
  project_id: string | null;
  enabled: boolean;
}

export async function fetchTools(): Promise<ToolsData> {
  return fetchJson<ToolsData>(projectUrl(TOOLS_PATH));
}

export function toggleSkill(skillId: string, scope?: SkillScope) {
  return request<SkillToggleResponse>(
    "PATCH",
    apiUrl(skillPath(skillId, "/toggle"), scopeParams(scope)),
  );
}

export function createSkill(
  skillId: string,
  name: string,
  description = "",
  scope: "shared" | "project" = "shared",
  projectId?: string,
) {
  return post<{ status: string; skill_id: string; name: string; scope: string }>(
    SKILLS_PATH,
    { skill_id: skillId, name, description, scope, project_id: projectId },
  );
}

export async function fetchSkillFiles(skillId: string, scope?: SkillScope) {
  return fetchJson<{ skill_id: string; files: Record<string, string> }>(
    apiUrl(skillPath(skillId, "/files"), scopeParams(scope)),
  );
}

export function updateSkillFiles(
  skillId: string,
  files: Record<string, string>,
  scope?: SkillScope,
) {
  return fetchJson<{ status: string; skill_id: string; enabled: boolean }>(
    apiUrl(skillPath(skillId, "/files"), scopeParams(scope)),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files }),
    },
  );
}

export function deleteSkill(skillId: string, scope?: SkillScope) {
  return request<{ status: string; skill_id: string }>(
    "DELETE",
    apiUrl(skillPath(skillId), scopeParams(scope)),
  );
}

export function reloadAllSkills() {
  return post<{ status: string; skills_count: number; skills: string[] }>(
    skillPath(undefined, "/reload"),
    {},
  );
}
