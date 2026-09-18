import { apiFetch, apiUrl, fetchJson, parseErrorMessage, put, request } from "./common";

// apiUrl / put / request 都會自己補上 /api/v1，這裡再寫一次會變成
// /api/v1/api/v1/... 然後 404。
const SETTING_PATH = "/settings/asr-provider";

export interface SystemSetting {
  key: string;
  /** 儲存的覆寫值；空字串代表沿用環境變數。 */
  value: string;
  /** 目前實際生效的值，無論來自覆寫或環境變數。 */
  effective: string;
  overridden: boolean;
  options: string[];
}

export async function fetchAsrProvider(): Promise<SystemSetting> {
  return fetchJson<SystemSetting>(apiUrl(SETTING_PATH));
}

export async function setAsrProvider(value: string): Promise<SystemSetting> {
  return put<SystemSetting>(SETTING_PATH, { value });
}

export async function clearAsrProvider(): Promise<SystemSetting> {
  return request<SystemSetting>("DELETE", SETTING_PATH);
}

export interface AsrPreview {
  text: string;
  provider: string;
}

/** 以目前生效的引擎轉寫一段錄音，讓操作者當場驗證選擇。 */
export async function previewAsr(clip: Blob): Promise<AsrPreview> {
  const form = new FormData();
  // 副檔名決定後端暫存檔的 suffix；瀏覽器錄的是 webm。
  form.append("file", clip, "preview.webm");
  const res = await apiFetch(apiUrl(`${SETTING_PATH}/preview`), {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await parseErrorMessage(res));
  return (await res.json()) as AsrPreview;
}
