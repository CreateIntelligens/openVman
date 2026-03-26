import { fetchJson, projectUrl, post, jsonRequest, personaPath, PERSONAS_PATH, getActiveProjectId } from "./common";

export interface PersonaSummary {
  persona_id: string;
  label: string;
  path: string;
  preview: string;
  is_default: boolean;
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

export async function fetchPersonas() {
  return fetchJson<PersonasResponse>(projectUrl(PERSONAS_PATH));
}

export function createPersona(personaId: string, label: string) {
  return post<PersonaCreateResponse>(PERSONAS_PATH, {
    persona_id: personaId,
    label,
    project_id: getActiveProjectId(),
  });
}

export function deletePersona(personaId: string) {
  return jsonRequest<{ status: string; persona_id: string }>(
    "DELETE",
    PERSONAS_PATH,
    { persona_id: personaId, project_id: getActiveProjectId() },
  );
}

export function clonePersona(sourcePersonaId: string, targetPersonaId: string) {
  return post<PersonaCloneResponse>(personaPath("/clone"), {
    source_persona_id: sourcePersonaId,
    target_persona_id: targetPersonaId,
    project_id: getActiveProjectId(),
  });
}
