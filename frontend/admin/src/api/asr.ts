import { apiFetch, apiUrl, fetchJson, parseErrorMessage, put } from "./common";

// apiUrl / put 會自己補上 /api/v1。
const MY_PROVIDER_PATH = "/settings/my-asr-provider";

/** 瀏覽器內建辨識。它不在伺服器的 provider 清單裡：辨識在使用者的裝置上
 *  發生，音檔不會送到後端。 */
export const BROWSER_ASR = "browser";

export interface MyAsrProvider {
  /** 使用者自己選的值；空字串代表沿用全站設定。 */
  value: string;
  /** 實際生效的值。選過但之後被收回授權時，這裡會回退成全站設定。 */
  effective: string;
  /** 這個帳號獲授權可選的引擎。 */
  allowed: string[];
}

export async function fetchMyAsrProvider(): Promise<MyAsrProvider> {
  return fetchJson<MyAsrProvider>(apiUrl(MY_PROVIDER_PATH));
}

export async function setMyAsrProvider(value: string): Promise<MyAsrProvider> {
  return put<MyAsrProvider>(MY_PROVIDER_PATH, { value });
}

export interface ServerTranscription {
  text: string;
  provider: string;
  elapsed_seconds?: number;
}

/** 以帳號選定的伺服器引擎轉寫一段錄音。
 *
 * 引擎由後端依帳號自己查，不由這裡指定——否則前端改個請求就能繞過授權。
 * 跟「語音」頁的試辨識不同：那個端點限 admin 且用全站設定，這個任何登入
 * 帳號都能用、用的是自己的選擇，行為才會跟虛擬人聊天室一致。
 */
export async function transcribeOnServer(
  clip: Blob,
  filename: string,
): Promise<ServerTranscription> {
  const form = new FormData();
  form.append("file", clip, filename);
  const res = await apiFetch(apiUrl("/asr/transcribe"), {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await parseErrorMessage(res));
  return (await res.json()) as ServerTranscription;
}
