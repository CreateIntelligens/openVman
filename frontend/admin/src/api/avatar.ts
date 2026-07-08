import {
  AVATAR_BACKGROUNDS_PATH,
  AVATAR_MASCOTS_PATH,
  AVATAR_PATH,
  apiUrl,
  fetchJson,
  itemPath,
  parseJson,
} from "./common";

export interface AvatarCharacter {
  char_id: string;
  label: string;
  has_video: boolean;
  has_data: boolean;
  size_bytes: number;
  updated_at: string;
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
}

export interface AvatarBackgroundListResponse {
  backgrounds: AvatarBackground[];
}

export interface AvatarBackgroundMutationResponse {
  status: string;
  background: AvatarBackground;
}

export interface AvatarMascot {
  mascot_id: string;
  label: string;
  engine: "2d" | "3d";
  model_url: string;
  vrm_url: string;
  thumbnail_url?: string;
  fit: "" | "half" | "full";
  builtin: boolean;
  size_bytes: number;
  updated_at: string;
}

export interface AvatarMascotListResponse {
  mascots: AvatarMascot[];
}

export interface AvatarMascotMutationResponse {
  status: string;
  mascot: AvatarMascot;
}

export async function fetchAvatarCharacters(): Promise<AvatarListResponse> {
  return fetchJson<AvatarListResponse>(apiUrl(AVATAR_PATH));
}

export interface UploadArgs {
  charId: string;
  label: string;
  video: File;
  data: File;
}

export async function uploadAvatarCharacter(
  args: UploadArgs,
): Promise<AvatarMutationResponse> {
  const form = new FormData();
  form.append("char_id", args.charId);
  form.append("label", args.label);
  form.append("video", args.video);
  form.append("data", args.data);
  const res = await fetch(apiUrl(AVATAR_PATH), { method: "POST", body: form });
  return parseJson<AvatarMutationResponse>(res);
}

export async function deleteAvatarCharacter(
  charId: string,
): Promise<{ status: string; char_id: string }> {
  const res = await fetch(apiUrl(itemPath(AVATAR_PATH, charId)), { method: "DELETE" });
  return parseJson<{ status: string; char_id: string }>(res);
}

export async function renameAvatarCharacter(
  charId: string,
  newCharId: string,
): Promise<AvatarMutationResponse> {
  const res = await fetch(apiUrl(`${itemPath(AVATAR_PATH, charId)}/rename`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_char_id: newCharId }),
  });
  return parseJson<AvatarMutationResponse>(res);
}

export async function updateAvatarCharacterLabel(
  charId: string,
  label: string,
): Promise<AvatarMutationResponse> {
  const res = await fetch(apiUrl(itemPath(AVATAR_PATH, charId)), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
  return parseJson<AvatarMutationResponse>(res);
}

export async function fetchAvatarBackgrounds(): Promise<AvatarBackgroundListResponse> {
  return fetchJson<AvatarBackgroundListResponse>(apiUrl(AVATAR_BACKGROUNDS_PATH));
}

export interface UploadBackgroundArgs {
  backgroundId: string;
  label: string;
  image: File;
}

export async function uploadAvatarBackground(
  args: UploadBackgroundArgs,
): Promise<AvatarBackgroundMutationResponse> {
  const form = new FormData();
  form.append("background_id", args.backgroundId);
  form.append("label", args.label);
  form.append("image", args.image);
  const res = await fetch(apiUrl(AVATAR_BACKGROUNDS_PATH), { method: "POST", body: form });
  return parseJson<AvatarBackgroundMutationResponse>(res);
}

export async function deleteAvatarBackground(
  backgroundId: string,
): Promise<{ status: string; background_id: string }> {
  const res = await fetch(apiUrl(itemPath(AVATAR_BACKGROUNDS_PATH, backgroundId)), {
    method: "DELETE",
  });
  return parseJson<{ status: string; background_id: string }>(res);
}

export async function updateAvatarBackgroundLabel(
  backgroundId: string,
  label: string,
): Promise<AvatarBackgroundMutationResponse> {
  const res = await fetch(apiUrl(itemPath(AVATAR_BACKGROUNDS_PATH, backgroundId)), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
  return parseJson<AvatarBackgroundMutationResponse>(res);
}

export async function fetchAvatarMascots(): Promise<AvatarMascotListResponse> {
  return fetchJson<AvatarMascotListResponse>(apiUrl(AVATAR_MASCOTS_PATH));
}

export interface UploadMascotArgs {
  mascotId: string;
  label: string;
  model: File;
  thumbnail?: File;
}

export async function uploadAvatarMascot(
  args: UploadMascotArgs,
): Promise<AvatarMascotMutationResponse> {
  const form = new FormData();
  form.append("mascot_id", args.mascotId);
  form.append("label", args.label);
  form.append("model", args.model);
  if (args.thumbnail) {
    form.append("thumbnail", args.thumbnail);
  }
  const res = await fetch(apiUrl(AVATAR_MASCOTS_PATH), {
    method: "POST",
    body: form,
  });
  return parseJson<AvatarMascotMutationResponse>(res);
}

export async function deleteAvatarMascot(
  mascotId: string,
): Promise<{ status: string; mascot_id: string }> {
  const res = await fetch(apiUrl(itemPath(AVATAR_MASCOTS_PATH, mascotId)), {
    method: "DELETE",
  });
  return parseJson<{ status: string; mascot_id: string }>(res);
}

export async function updateAvatarMascotLabel(
  mascotId: string,
  label: string,
): Promise<AvatarMascotMutationResponse> {
  const res = await fetch(apiUrl(itemPath(AVATAR_MASCOTS_PATH, mascotId)), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
  return parseJson<AvatarMascotMutationResponse>(res);
}

export async function uploadAvatarMascotThumbnail(
  mascotId: string,
  thumbnail: File,
): Promise<AvatarMascotMutationResponse> {
  const form = new FormData();
  form.append("thumbnail", thumbnail);
  const res = await fetch(apiUrl(`${itemPath(AVATAR_MASCOTS_PATH, mascotId)}/thumbnail`), {
    method: "POST",
    body: form,
  });
  return parseJson<AvatarMascotMutationResponse>(res);
}
