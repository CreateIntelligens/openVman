import { fetchJson, apiUrl, post, jsonRequest, request, skillPath, TOOLS_PATH, SKILLS_PATH } from "./common";

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
  enabled: boolean;
  tools: string[];
  warnings: string[];
}

export interface ToolsData {
  tools: ToolInfo[];
  skill_tools: ToolInfo[];
  skills: SkillInfo[];
}

export async function fetchTools(): Promise<ToolsData> {
  return fetchJson<ToolsData>(apiUrl(TOOLS_PATH));
}

export function toggleSkill(skillId: string) {
  return request<{ status: string; skill_id: string; enabled: boolean }>(
    "PATCH",
    skillPath(skillId, "/toggle"),
  );
}

export function createSkill(skillId: string, name: string, description = "") {
  return post<{ status: string; skill_id: string; name: string }>(
    SKILLS_PATH,
    { skill_id: skillId, name, description },
  );
}

export async function fetchSkillFiles(skillId: string) {
  return fetchJson<{ skill_id: string; files: Record<string, string> }>(
    apiUrl(skillPath(skillId, "/files")),
  );
}

export function updateSkillFiles(skillId: string, files: Record<string, string>) {
  return jsonRequest<{ status: string; skill_id: string; enabled: boolean }>(
    "PUT",
    skillPath(skillId, "/files"),
    { files },
  );
}

export function deleteSkill(skillId: string) {
  return request<{ status: string; skill_id: string }>(
    "DELETE",
    skillPath(skillId),
  );
}

export function reloadAllSkills() {
  return post<{ status: string; skills_count: number; skills: string[] }>(
    skillPath(undefined, "/reload"),
    {},
  );
}
