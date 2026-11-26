/**
 * 人設開場白：取得與「同一組只播一次」的排程。純函式、不碰 Vue，方便單獨測。
 */

export interface Greeting {
  text: string
  voice?: string
}

export interface GreetingKey {
  language: string
  personaId: string
  projectId: string
}

type Fetcher = (input: string) => Promise<Pick<Response, 'ok' | 'status' | 'json'>>

export const GREETING_ENDPOINT = '/api/v1/personas/greeting'

/** 沒設這個語言的開場白（404）或任何非 2xx 都回 null；網路錯誤照樣拋出，讓呼叫端決定要不要重試。 */
export async function fetchGreeting(fetcher: Fetcher, key: GreetingKey): Promise<Greeting | null> {
  const query = new URLSearchParams({
    language: key.language,
    persona_id: key.personaId,
    project_id: key.projectId,
  })
  const res = await fetcher(`${GREETING_ENDPOINT}?${query.toString()}`)
  if (!res.ok) return null
  const body = (await res.json().catch(() => null)) as { text?: unknown; voice?: unknown } | null
  if (!body || typeof body.text !== 'string' || !body.text.trim()) return null
  return {
    text: body.text,
    ...(typeof body.voice === 'string' && body.voice ? { voice: body.voice } : {}),
  }
}

interface SchedulerDeps {
  /** 目前該播的那一組；還沒準備好（人物沒載入、沒指定語言）回 null。 */
  current: () => GreetingKey | null
  fetch: (key: GreetingKey) => Promise<Greeting | null>
  play: (greeting: Greeting) => void | Promise<void>
}

const identity = (key: GreetingKey) => `${key.language}|${key.personaId}|${key.projectId}`

export function createGreetingScheduler({ current, fetch, play }: SchedulerDeps) {
  const handled = new Set<string>()

  /** 狀態改變時呼叫：這一組還沒處理過才取開場白並播出；失敗一律靜默。 */
  async function sync(): Promise<void> {
    const key = current()
    if (!key) return
    const id = identity(key)
    if (handled.has(id)) return
    handled.add(id)
    let greeting: Greeting | null
    try {
      greeting = await fetch(key)
    } catch {
      // 網路暫時失敗不算處理過，下次狀態變動可以再試。
      handled.delete(id)
      return
    }
    if (!greeting) return
    // 等回應期間語言、人設換了或人物不在了：這份已經過期，不播，也讓這一組之後還有機會播。
    const now = current()
    if (!now || identity(now) !== id) {
      handled.delete(id)
      return
    }
    try {
      await play(greeting)
    } catch (error) {
      console.warn('[greeting] playback failed:', error)
    }
  }

  /** 換下一位來賓（展示機台）：同一組也要再播一次。 */
  function reset(): void {
    handled.clear()
  }

  return { sync, reset }
}
