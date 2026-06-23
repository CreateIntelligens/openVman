import { apiUrl, fetchJson, itemPath, AVATAR_PATH, parseJson } from "./common";

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
