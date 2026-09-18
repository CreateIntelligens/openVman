import { apiUrl, fetchJson, put, request } from "./common";

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
  return fetchJson<SystemSetting>(apiUrl("/api/v1/settings/asr-provider"));
}

export async function setAsrProvider(value: string): Promise<SystemSetting> {
  return put<SystemSetting>("/api/v1/settings/asr-provider", { value });
}

export async function clearAsrProvider(): Promise<SystemSetting> {
  return request<SystemSetting>("DELETE", "/api/v1/settings/asr-provider");
}
