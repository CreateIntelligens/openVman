import { apiFetch, fetchJson, parseJson } from "./http"

const MY_PROVIDER_PATH = "/api/v1/settings/my-asr-provider"

/** 瀏覽器內建辨識。它不在伺服器的 provider 清單裡：辨識在使用者的裝置上
 *  發生，音檔不會送到後端，所以也不走伺服器的 fallback chain。 */
export const BROWSER_ASR = "browser"

export interface MyAsrProvider {
  /** 使用者自己選的值；空字串代表沿用全站設定。 */
  value: string
  /** 實際生效的值。選過但之後被管理者關閉時，這裡會回退成全站設定。 */
  effective: string
  /** 管理者開放給使用者自選的引擎。 */
  allowed: string[]
}

export async function fetchMyAsrProvider(): Promise<MyAsrProvider> {
  return fetchJson<MyAsrProvider>(MY_PROVIDER_PATH)
}

export async function setMyAsrProvider(value: string): Promise<MyAsrProvider> {
  return parseJson<MyAsrProvider>(await apiFetch(MY_PROVIDER_PATH, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  }))
}

export interface ServerTranscription {
  text: string
  provider: string
  elapsed_seconds?: number
}

/** Transcribe a clip with the account's chosen server engine.
 *
 * 走跟後台試辨識同一條 transcribe()，所以聊天室的行為就是後台測過的行為，含
 * fallback。這個端點任何登入帳號都能用，後台那個限 admin。
 * 引擎由後端依帳號自己查，不由這裡指定——否則前端改個請求就能繞過管理者的
 * 開放清單。
 */
export async function transcribeOnServer(
  clip: Blob,
  filename: string,
): Promise<ServerTranscription> {
  const form = new FormData()
  form.append("file", clip, filename)
  return parseJson<ServerTranscription>(await apiFetch(
    "/api/v1/asr/transcribe",
    { method: "POST", body: form },
  ))
}
