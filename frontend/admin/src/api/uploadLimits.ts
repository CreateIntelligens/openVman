import { apiUrl, fetchJson } from "./common";

/** Server-side upload limits from GET /api/v1/uploads/limits. */
export interface UploadLimits {
  document_max_upload_bytes: number;
  asr_max_upload_bytes: number;
  asr_max_duration_seconds: number;
  avatar_max_upload_bytes: number;
  avatar_background_max_upload_bytes: number;
  avatar_mascot_max_upload_bytes: number;
  avatar_mascot_thumbnail_max_upload_bytes: number;
  avatar_source_max_upload_bytes: number;
  avatar_source_image_max_upload_bytes: number;
  avatar_source_max_duration_seconds: number;
  image_max_side_px: number;
}

const MB = 1024 * 1024;

// 後端預設值；拿到伺服器設定前先用這組顯示提示，送出前仍以伺服器值為準。
export const DEFAULT_UPLOAD_LIMITS: UploadLimits = {
  document_max_upload_bytes: 100 * MB,
  asr_max_upload_bytes: 25 * MB,
  asr_max_duration_seconds: 300,
  avatar_max_upload_bytes: 100 * MB,
  avatar_background_max_upload_bytes: 25 * MB,
  avatar_mascot_max_upload_bytes: 100 * MB,
  avatar_mascot_thumbnail_max_upload_bytes: 10 * MB,
  avatar_source_max_upload_bytes: 200 * MB,
  avatar_source_image_max_upload_bytes: 25 * MB,
  avatar_source_max_duration_seconds: 60,
  image_max_side_px: 8192,
};

export async function fetchUploadLimits(): Promise<UploadLimits> {
  const limits = await fetchJson<Partial<UploadLimits>>(apiUrl("/uploads/limits"));
  return { ...DEFAULT_UPLOAD_LIMITS, ...limits };
}
