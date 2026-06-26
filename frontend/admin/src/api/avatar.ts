import {
  apiUrl,
  fetchJson,
  itemPath,
  AVATAR_BACKGROUNDS_PATH,
  AVATAR_PATH,
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

export async function fetchAvatarCharacters() {
  return fetchJson<AvatarListResponse>(apiUrl(AVATAR_PATH));
}

export interface UploadArgs {
  charId: string;
  label: string;
  video: File;
  data: File;
}

export async function uploadAvatarCharacter(args: UploadArgs) {
  const form = new FormData();
  form.append("char_id", args.charId);
  form.append("label", args.label);
  form.append("video", args.video);
  form.append("data", args.data);
  const res = await fetch(apiUrl(AVATAR_PATH), { method: "POST", body: form });
  return parseJson<AvatarMutationResponse>(res);
}

export async function deleteAvatarCharacter(charId: string) {
  const res = await fetch(apiUrl(itemPath(AVATAR_PATH, charId)), { method: "DELETE" });
  return parseJson<{ status: string; char_id: string }>(res);
}

export async function renameAvatarCharacter(charId: string, newCharId: string) {
  const res = await fetch(apiUrl(`${itemPath(AVATAR_PATH, charId)}/rename`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_char_id: newCharId }),
  });
  return parseJson<AvatarMutationResponse>(res);
}

export async function updateAvatarCharacterLabel(charId: string, label: string) {
  const res = await fetch(apiUrl(itemPath(AVATAR_PATH, charId)), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
  return parseJson<AvatarMutationResponse>(res);
}

export async function fetchAvatarBackgrounds() {
  return fetchJson<AvatarBackgroundListResponse>(apiUrl(AVATAR_BACKGROUNDS_PATH));
}

export interface UploadBackgroundArgs {
  backgroundId: string;
  label: string;
  image: File;
}

export async function uploadAvatarBackground(args: UploadBackgroundArgs) {
  const form = new FormData();
  form.append("background_id", args.backgroundId);
  form.append("label", args.label);
  form.append("image", args.image);
  const res = await fetch(apiUrl(AVATAR_BACKGROUNDS_PATH), { method: "POST", body: form });
  return parseJson<AvatarBackgroundMutationResponse>(res);
}

export async function deleteAvatarBackground(backgroundId: string) {
  const res = await fetch(apiUrl(itemPath(AVATAR_BACKGROUNDS_PATH, backgroundId)), {
    method: "DELETE",
  });
  return parseJson<{ status: string; background_id: string }>(res);
}

export async function updateAvatarBackgroundLabel(backgroundId: string, label: string) {
  const res = await fetch(apiUrl(itemPath(AVATAR_BACKGROUNDS_PATH, backgroundId)), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
  return parseJson<AvatarBackgroundMutationResponse>(res);
}
