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

/**
 * 空字串的 content_hash（Brain 的 sha256 前 16 碼）。檔案還不存在時存檔帶這個值：
 * 兩個人同時第一次建立，後存的會收到 409，不會蓋掉先存的。Brain 測試釘住同一個值。
 */
export const EMPTY_CONTENT_HASH = "e3b0c44298fc1c14";

export interface PersonaDocument {
  content: string;
  /** 存檔時當 base_hash 帶回；舊版 Brain 沒有這個欄位。 */
  content_hash?: string;
}

export interface PersonaDocumentSaved {
  status: string;
  /** 剛存好的版本；下一次存檔帶這個值。 */
  content_hash?: string;
}

/** 帶了 base_hash，檔案在載入後被別處改過就會收到 409，不會整份蓋掉別人的修改。 */
function documentBody(personaId: string, content: string, projectId?: string, baseHash?: string) {
  return {
    project_id: inProject(projectId),
    persona_id: personaId,
    content,
    ...(baseHash ? { base_hash: baseHash } : {}),
  };
}

export function fetchPersonaSoul(personaId: string, projectId?: string) {
  return get<PersonaDocument>(personaPath("/soul"), {
    persona_id: personaId, project_id: inProject(projectId),
  });
}

export function savePersonaSoul(personaId: string, content: string, projectId?: string, baseHash?: string) {
  return put<PersonaDocumentSaved>(personaPath("/soul"), documentBody(personaId, content, projectId, baseHash));
}

/** 角色的工作規則（AGENTS.md）。角色還沒有自己的檔案時 `exists` 是 false，版本是空字串的雜湊。 */
export async function fetchPersonaAgents(
  personaId: string, projectId?: string,
): Promise<PersonaDocument & { exists: boolean }> {
  try {
    const response = await get<PersonaDocument>(personaPath("/agents"), {
      persona_id: personaId, project_id: inProject(projectId),
    });
    return { content: response.content, exists: true, content_hash: response.content_hash };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { content: "", exists: false, content_hash: EMPTY_CONTENT_HASH };
    }
    throw error;
  }
}

export function savePersonaAgents(personaId: string, content: string, projectId?: string, baseHash?: string) {
  return put<PersonaDocumentSaved>(personaPath("/agents"), documentBody(personaId, content, projectId, baseHash));
}

export interface GuardrailsResponse {
  /** 專案沒設定（或檔案是連結）時是空字串。 */
  content: string;
  /** 平台的建議內容，給有權限的內部帳號一鍵帶入。 */
  template?: string;
  /** 檔案是連結：AI 不採用，也不能從這裡改。 */
  linked?: boolean;
  max_chars?: number;
  /** 存檔時帶回；別處已經改過就會被拒絕，不會蓋掉較新的內容。還沒有檔案時是空字串的雜湊。 */
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
