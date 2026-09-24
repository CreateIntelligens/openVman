/**
 * useLanguageRoutes — 知識庫語言分流的前台臨時開關。
 *
 * 後台在知識庫設定勾的分流是上限（GET /api/v1/language-routes）；前台只能在這個
 * 範圍內臨時關掉或勾回，存在這台瀏覽器、依專案分開。送 ASR／TTS／聊天時帶
 * 目前開著的分流，後端再跟後台設定取交集。至少要留一條。
 *
 * 台語分流開著時：ASR 由後端改用 Breeze、瀏覽器內建辨識停用（它聽不懂台語），
 * TTS 原本不是 VoxCPM／CosyVoice 就改用 VoxCPM。
 */
import { computed, ref, watch } from 'vue'

import { apiFetch, parseJson } from '../api/http'
import { STORAGE_KEYS, readPref, writePref } from '../utils/storageUtils'

export const LANGUAGE_ROUTE_LABELS: Record<string, string> = {
  zh: '中文',
  en: 'English',
  es: 'Español',
  nan: '台語',
}
export const TAIWANESE_ROUTE = 'nan'
const TAIWANESE_TTS_PROVIDERS = ['voxcpm', 'cosyvoice']

function readOffMap(): Record<string, string[]> {
  try {
    const parsed = JSON.parse(readPref(STORAGE_KEYS.LANGUAGE_ROUTES_OFF, '{}'))
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function useLanguageRoutes(projectId: () => string) {
  // 後台勾的分流，至少一條、不一定是中文。
  const available = ref<string[]>(['zh'])
  const offMap = ref<Record<string, string[]>>(readOffMap())

  async function load(): Promise<void> {
    try {
      const res = await apiFetch(
        `/api/v1/language-routes?project_id=${encodeURIComponent(projectId())}`,
      )
      const data = await parseJson<{ available?: string[] }>(res)
      available.value = data.available?.length ? data.available : ['zh']
    } catch {
      // 讀不到就當只有中文，不該因此不能講話。
      available.value = ['zh']
    }
  }

  watch(projectId, () => void load(), { immediate: true })

  const off = computed(() => new Set(offMap.value[projectId()] ?? []))
  const active = computed(() => {
    const on = available.value.filter((route) => !off.value.has(route))
    // 至少留一條；舊資料或後台改了設定導致全關時，退回後台第一條。
    return on.length ? on : available.value.slice(0, 1)
  })
  const taiwaneseOn = computed(() => active.value.includes(TAIWANESE_ROUTE))

  function toggle(route: string): void {
    if (!available.value.includes(route)) return
    const current = new Set(off.value)
    if (current.has(route)) current.delete(route)
    else if (active.value.length > 1) current.add(route)
    else return
    offMap.value = { ...offMap.value, [projectId()]: [...current] }
    writePref(STORAGE_KEYS.LANGUAGE_ROUTES_OFF, JSON.stringify(offMap.value))
  }

  /** 每次 ASR 上傳附加的表單欄位。 */
  function asrFormFields(): Record<string, string> {
    return { project_id: projectId(), language_routes: active.value.join(',') }
  }

  /**
   * 這一輪要用的 TTS provider：台語分流開著、而且使用者這句是語音被判成台語，
   * 才換 VoxCPM；打字、快速問答、講華語都照原本選的。原本就是 VoxCPM／CosyVoice 不動。
   */
  function ttsProviderFor(
    provider: string,
    speechLanguage: string | null,
  ): { provider: string; switched: boolean } {
    if (
      !taiwaneseOn.value
      || speechLanguage !== TAIWANESE_ROUTE
      || TAIWANESE_TTS_PROVIDERS.includes(provider)
    ) {
      return { provider, switched: false }
    }
    return { provider: 'voxcpm', switched: true }
  }

  return { available, active, taiwaneseOn, toggle, load, asrFormFields, ttsProviderFor }
}
