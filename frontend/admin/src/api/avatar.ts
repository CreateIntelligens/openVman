import {
  AVATAR_BACKGROUNDS_PATH,
  AVATAR_PATH,
  apiUrl,
  fetchJson,
  itemPath,
} from "./common";

export interface AvatarCharacter {
  char_id: string;
  label: string;
  has_video: boolean;
  has_data: boolean;
  size_bytes: number;
  updated_at: string;
  owner_project_id?: string | null;
  source?: "system" | "project" | "assigned" | "orphan";
}

export interface AvatarListResponse {
  characters: AvatarCharacter[];
}

export interface AvatarMutationResponse {
  status: string;
  character: AvatarCharacter;
}

export interface AvatarBackground {
  background_id: string;
  label: string;
  url: string;
  mime_type: string;
  size_bytes: number;
  updated_at: string;
  owner_project_id?: string | null;
  source?: "system" | "project" | "assigned" | "orphan";
}

export interface AvatarBackgroundListResponse {
  backgrounds: AvatarBackground[];
}

export interface AvatarBackgroundMutationResponse {
  status: string;
  background: AvatarBackground;
}

export async function fetchAvatarCharacters(projectId?: string): Promise<AvatarListResponse> {
  const url = projectId
    ? `${AVATAR_PATH}?project_id=${encodeURIComponent(projectId)}`
    : AVATAR_PATH;
  return fetchJson<AvatarListResponse>(apiUrl(url));
}

export interface UploadArgs {
  charId: string;
  label: string;
  video: File;
  data: File;
  projectId?: string;
}

export async function uploadAvatarCharacter(
  args: UploadArgs,
): Promise<AvatarMutationResponse> {
  const form = new FormData();
  form.append("char_id", args.charId);
  form.append("label", args.label);
  form.append("video", args.video);
  form.append("data", args.data);
  if (args.projectId) {
    form.append("project_id", args.projectId);
  }
  return fetchJson<AvatarMutationResponse>(apiUrl(AVATAR_PATH), {
    method: "POST",
    body: form,
  });
}

export type AvatarJobState = "queued" | "running" | "done" | "failed";

export interface AvatarJob {
  job_id: string;
  state: AvatarJobState;
  stage?: string;
  done?: number;
  total?: number;
  error?: string;
  char_id: string;
  label: string;
  project_id?: string | null;
  source_name?: string;
  created_at?: number;
  updated_at?: number;
  frame_count?: number;
  width?: number;
  height?: number;
  character?: AvatarCharacter;
}

export interface AvatarJobListResponse {
  jobs: AvatarJob[];
}

interface SubmitJobArgs {
  charId: string;
  label: string;
  video: File;
  projectId?: string;
}

/** 把說話影片交給 avatar-pipeline 轉成素材包；回傳排進佇列的工作。 */
export async function submitAvatarCharacterJob(
  args: SubmitJobArgs,
): Promise<{ status: string; job: AvatarJob }> {
  const form = new FormData();
  form.append("char_id", args.charId);
  form.append("label", args.label);
  form.append("video", args.video);
  if (args.projectId) {
    form.append("project_id", args.projectId);
  }
  return fetchJson<{ status: string; job: AvatarJob }>(apiUrl(`${AVATAR_PATH}/jobs`), {
    method: "POST",
    body: form,
  });
}

export async function fetchAvatarCharacterJobs(): Promise<AvatarJobListResponse> {
  return fetchJson<AvatarJobListResponse>(apiUrl(`${AVATAR_PATH}/jobs`));
}

export async function deleteAvatarCharacterJob(jobId: string): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(apiUrl(`${AVATAR_PATH}/jobs/${encodeURIComponent(jobId)}`), {
    method: "DELETE",
  });
}

export async function deleteAvatarCharacter(
  charId: string,
): Promise<{ status: string; char_id: string }> {
  return fetchJson<{ status: string; char_id: string }>(
    apiUrl(itemPath(AVATAR_PATH, charId)),
    { method: "DELETE" },
  );
}

export async function renameAvatarCharacter(
  charId: string,
  newCharId: string,
): Promise<AvatarMutationResponse> {
  return fetchJson<AvatarMutationResponse>(
    apiUrl(`${itemPath(AVATAR_PATH, charId)}/rename`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_char_id: newCharId }),
    },
  );
}

export async function updateAvatarCharacterLabel(
  charId: string,
  label: string,
): Promise<AvatarMutationResponse> {
  return fetchJson<AvatarMutationResponse>(apiUrl(itemPath(AVATAR_PATH, charId)), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
}

export async function fetchAvatarBackgrounds(projectId?: string): Promise<AvatarBackgroundListResponse> {
  const url = projectId
    ? `${AVATAR_BACKGROUNDS_PATH}?project_id=${encodeURIComponent(projectId)}`
    : AVATAR_BACKGROUNDS_PATH;
  return fetchJson<AvatarBackgroundListResponse>(apiUrl(url));
}

export interface UploadBackgroundArgs {
  backgroundId: string;
  label: string;
  image: File;
  projectId?: string;
}

export async function uploadAvatarBackground(
  args: UploadBackgroundArgs,
): Promise<AvatarBackgroundMutationResponse> {
  const form = new FormData();
  form.append("background_id", args.backgroundId);
  form.append("label", args.label);
  form.append("image", args.image);
  if (args.projectId) {
    form.append("project_id", args.projectId);
  }
  return fetchJson<AvatarBackgroundMutationResponse>(apiUrl(AVATAR_BACKGROUNDS_PATH), {
    method: "POST",
    body: form,
  });
}

export async function deleteAvatarBackground(
  backgroundId: string,
): Promise<{ status: string; background_id: string }> {
  return fetchJson<{ status: string; background_id: string }>(
    apiUrl(itemPath(AVATAR_BACKGROUNDS_PATH, backgroundId)),
    { method: "DELETE" },
  );
}

export async function updateAvatarBackgroundLabel(
  backgroundId: string,
  label: string,
): Promise<AvatarBackgroundMutationResponse> {
  return fetchJson<AvatarBackgroundMutationResponse>(
    apiUrl(itemPath(AVATAR_BACKGROUNDS_PATH, backgroundId)),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label }),
    },
  );
}
