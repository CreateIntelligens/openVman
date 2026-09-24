/**
 * 伺服器 ASR API Client
 *
 * 提供查詢/設定使用者的 ASR 引擎設定，以及上傳音訊進行後端辨識。
 * 遵循完整後端 API 路徑 `/api/v1/...`。
 */

import type { HttpAdapter } from '../http'
import { extractErrorMessage } from '../http'

export const MY_ASR_PROVIDER_PATH = '/api/v1/settings/my-asr-provider'
export const TRANSCRIBE_PATH = '/api/v1/asr/transcribe'

export interface MyAsrProvider {
  /** 使用者自選的值；空字串代表沿用全站設定。 */
  value: string
  /** 實際生效的值。選過但之後被管理員關閉時，會回退為全站設定。 */
  effective: string
  /** 管理員開放給使用者自選的引擎清單。 */
  allowed: string[]
}

export interface ServerTranscription {
  text: string
  provider: string
  elapsed_seconds?: number
  /** 後端聽出的語言；目前只有台語分流開著時會回 "nan"。轉錄文字看不出台語。 */
  language?: string | null
  /** 實際生效的語言分流（後台設定與 language_routes 的交集）。 */
  language_routes?: string[]
}

/** 轉錄結果附帶的資訊，交給 onResult 的第二個參數。 */
export interface TranscriptionMeta {
  language?: string | null
}

/** 每次上傳時附加的表單欄位（例如 project_id、language_routes）。 */
export type TranscribeFormFields = () => Record<string, string>

async function checkOk(res: Response, http: HttpAdapter): Promise<void> {
  if (!res.ok) {
    const message = http.parseError
      ? await http.parseError(res)
      : await extractErrorMessage(res)
    throw new Error(message)
  }
}

/**
 * 取得當前帳號的 ASR 設定
 */
export async function fetchMyAsrProvider(http: HttpAdapter): Promise<MyAsrProvider> {
  const res = await http.request(MY_ASR_PROVIDER_PATH)
  await checkOk(res, http)
  return (await res.json()) as MyAsrProvider
}

/**
 * 更新當前帳號的 ASR 設定
 */
export async function setMyAsrProvider(
  http: HttpAdapter,
  value: string,
): Promise<MyAsrProvider> {
  const res = await http.request(MY_ASR_PROVIDER_PATH, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
  await checkOk(res, http)
  return (await res.json()) as MyAsrProvider
}

/**
 * 上傳音訊檔案至伺服器進行語音辨識
 *
 * 由後端依當前使用者帳號選定的引擎轉寫，前端不指定引擎，維持既有授權安全設計。
 */
export async function transcribeOnServer(
  http: HttpAdapter,
  clip: Blob,
  filename: string,
  formFields?: TranscribeFormFields,
): Promise<ServerTranscription> {
  const form = new FormData()
  form.append('file', clip, filename)
  for (const [key, value] of Object.entries(formFields?.() ?? {})) {
    form.append(key, value)
  }
  const res = await http.request(TRANSCRIBE_PATH, {
    method: 'POST',
    body: form,
  })
  await checkOk(res, http)
  return (await res.json()) as ServerTranscription
}
