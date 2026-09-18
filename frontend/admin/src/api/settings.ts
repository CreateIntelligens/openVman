import { apiUrl, fetchJson, put, request } from "./common";

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
