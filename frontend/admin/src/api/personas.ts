import {
  ApiError,
  PERSONAS_PATH,
  fetchJson,
  get,
  getActiveProjectId,
  jsonRequest,
  personaPath,
  post,
  projectUrl,
  put,
} from "./common";

export interface PersonaSummary {
  persona_id: string;
  label: string;
  path?: string;
  preview?: string;
  is_default: boolean;
  avatar_char_id?: string | null;
}

export interface PersonasResponse {
  personas: PersonaSummary[];
  persona_count: number;
}

export interface PersonaCreateResponse {
  status: string;
  persona: PersonaSummary;
  files: string[];
}

export interface PersonaCloneResponse extends PersonaCreateResponse {
  source_persona_id: string;
}

export async function fetchPersonas(): Promise<PersonasResponse> {
  return fetchJson<PersonasResponse>(projectUrl(PERSONAS_PATH));
}

export function createPersona(
  personaId: string,
  label: string,
): Promise<PersonaCreateResponse> {
  return post<PersonaCreateResponse>(PERSONAS_PATH, {
    persona_id: personaId,
    label,
    project_id: getActiveProjectId(),
  });
}

export function deletePersona(
  personaId: string,
): Promise<{ status: string; persona_id: string }> {
  return jsonRequest<{ status: string; persona_id: string }>(
    "DELETE",
    PERSONAS_PATH,
    { persona_id: personaId, project_id: getActiveProjectId() },
  );
}

export function clonePersona(
  sourcePersonaId: string,
  targetPersonaId: string,
): Promise<PersonaCloneResponse> {
  return post<PersonaCloneResponse>(personaPath("/clone"), {
    source_persona_id: sourcePersonaId,
    target_persona_id: targetPersonaId,
    project_id: getActiveProjectId(),
  });
}

export function setPersonaAvatar(
  personaId: string,
  avatarCharId: string | null,
): Promise<{
  status: string;
  persona_id: string;
  avatar_char_id: string | null;
}> {
  return post<{
    status: string;
    persona_id: string;
    avatar_char_id: string | null;
  }>(personaPath("/avatar"), {
    persona_id: personaId,
    avatar_char_id: avatarCharId,
    project_id: getActiveProjectId(),
  });
}

// 角色管理的讀寫一律帶明確的專案：存檔途中切換專案時，後面的請求不能改用新專案。
const inProject = (projectId?: string) => projectId ?? getActiveProjectId();

export function fetchPersonaSoul(personaId: string, projectId?: string) {
  return get<{ content: string }>(personaPath("/soul"), {
    persona_id: personaId, project_id: inProject(projectId),
  });
}

export function savePersonaSoul(personaId: string, content: string, projectId?: string) {
  return put<{ status: string }>(personaPath("/soul"), {
    project_id: inProject(projectId),
    persona_id: personaId,
    content,
  });
}

/** 角色的工作規則（AGENTS.md）。角色還沒有自己的檔案時 `exists` 是 false。 */
export async function fetchPersonaAgents(personaId: string, projectId?: string) {
  try {
    const response = await get<{ content: string }>(personaPath("/agents"), {
      persona_id: personaId, project_id: inProject(projectId),
    });
    return { content: response.content, exists: true };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return { content: "", exists: false };
    throw error;
  }
}

export function savePersonaAgents(personaId: string, content: string, projectId?: string) {
  return put<{ status: string }>(personaPath("/agents"), {
    project_id: inProject(projectId),
    persona_id: personaId,
    content,
  });
}

export interface GuardrailsResponse {
  /** 專案沒設定（或檔案是連結）時是空字串。 */
  content: string;
  /** 平台的建議內容，給有權限的內部帳號一鍵帶入。 */
  template?: string;
  /** 檔案是連結：AI 不採用，也不能從這裡改。 */
  linked?: boolean;
  max_chars?: number;
  /** 存檔時帶回；別處已經改過就會被拒絕，不會蓋掉較新的內容。 */
  content_hash?: string;
}

/** 專案的保護規則（GUARDRAILS.md），只讀；內部帳號改的時候走工作區文件 API。 */
export function fetchGuardrails(projectId?: string) {
  return get<GuardrailsResponse>(personaPath("/guardrails"), { project_id: inProject(projectId) });
}

export const GUARDRAILS_PATH = "GUARDRAILS.md";

export type GreetingLanguage = "zh" | "en" | "es" | "ja" | "ko";

export interface PersonaLanguageSettings {
  persona_id: string;
  greetings: Partial<Record<GreetingLanguage, string>>;
  voices: Partial<Record<GreetingLanguage, string>>;
}

export function fetchPersonaLanguageSettings(personaId: string, projectId?: string) {
  return get<PersonaLanguageSettings>(personaPath("/language-settings"), {
    persona_id: personaId, project_id: inProject(projectId),
  });
}

/** 整份取代：沒寫在 greetings／voices 裡的語言就是清掉。 */
export function savePersonaLanguageSettings(
  personaId: string,
  greetings: PersonaLanguageSettings["greetings"],
  voices: PersonaLanguageSettings["voices"],
  projectId?: string,
) {
  return put<PersonaLanguageSettings>(personaPath("/language-settings"), {
    persona_id: personaId,
    project_id: inProject(projectId),
    greetings,
    voices,
  });
}

/** 改人設的顯示名稱；預設人設也可以。 */
export function setPersonaLabel(personaId: string, label: string, projectId?: string) {
  return put<{ persona_id: string; label: string }>(personaPath("/label"), {
    persona_id: personaId,
    project_id: inProject(projectId),
    label,
  });
}
