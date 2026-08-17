import {
  AVATAR_BACKGROUNDS_PATH,
  AVATAR_MASCOTS_PATH,
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
  return fetchJson<AvatarMutationResponse>(apiUrl(AVATAR_PATH), {
    method: "POST",
    body: form,
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
  return fetchJson<AvatarMascotMutationResponse>(apiUrl(AVATAR_MASCOTS_PATH), {
    method: "POST",
    body: form,
  });
}

export async function deleteAvatarMascot(
  mascotId: string,
): Promise<{ status: string; mascot_id: string }> {
  return fetchJson<{ status: string; mascot_id: string }>(
    apiUrl(itemPath(AVATAR_MASCOTS_PATH, mascotId)),
    { method: "DELETE" },
  );
}

export async function updateAvatarMascotLabel(
  mascotId: string,
  label: string,
): Promise<AvatarMascotMutationResponse> {
  return fetchJson<AvatarMascotMutationResponse>(
    apiUrl(itemPath(AVATAR_MASCOTS_PATH, mascotId)),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label }),
    },
  );
}

export async function uploadAvatarMascotThumbnail(
  mascotId: string,
  thumbnail: File,
): Promise<AvatarMascotMutationResponse> {
  const form = new FormData();
  form.append("thumbnail", thumbnail);
  return fetchJson<AvatarMascotMutationResponse>(
    apiUrl(`${itemPath(AVATAR_MASCOTS_PATH, mascotId)}/thumbnail`),
    {
      method: "POST",
      body: form,
    },
  );
}
