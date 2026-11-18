import {
  apiUrl,
  fetchJson,
  getActiveProjectId,
  post,
  projectUrl,
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

// 範圍一律明寫：Brain 沒收到 scope 時會先找專案技能、找不到才落到共用的。
// 共用技能也要帶目前專案，後端靠它確認這個帳號看得到哪個專案。
function scopeParams(scope?: SkillScope): QueryParams {
  const skillScope = scope?.scope ?? "shared";
  const projectId = skillScope === "project" && scope?.project_id
    ? scope.project_id
    : getActiveProjectId();
  return { scope: skillScope, project_id: projectId };
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
  return fetchJson<SkillToggleResponse>(
    apiUrl(skillPath(skillId, "/toggle"), scopeParams(scope)),
    { method: "PATCH" },
  );
}

// 共用技能要改 repo 再部署，後台只建立專案技能。
export function createSkill(
  skillId: string,
  name: string,
  description = "",
  projectId: string = getActiveProjectId(),
) {
  return post<{ status: string; skill_id: string; name: string; scope: string }>(
    SKILLS_PATH,
    { skill_id: skillId, name, description, scope: "project", project_id: projectId },
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
  return fetchJson<{ status: string; skill_id: string }>(
    apiUrl(skillPath(skillId), scopeParams(scope)),
    { method: "DELETE" },
  );
}

export function reloadAllSkills() {
  return fetchJson<{ status: string; skills_count: number; skills: string[] }>(
    projectUrl(skillPath(undefined, "/reload")),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    },
  );
}
