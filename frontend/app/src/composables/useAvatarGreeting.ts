import { watch } from 'vue'
import { apiFetch } from '../api/http'
import { createGreetingScheduler, fetchGreeting, type Greeting, type GreetingKey } from './greeting'

interface GreetingOptions {
  /** 目前該播的那一組（語言、人設、專案）；人物沒就緒或沒指定語言時回 null。 */
  current: () => GreetingKey | null
  play: (greeting: Greeting) => void | Promise<void>
  activity?: () => number
}

/** 人物就緒後、以及語言或人設改變時播一次開場白；不進對話紀錄、不呼叫模型。 */
export function useAvatarGreeting({ current, play, activity }: GreetingOptions) {
  const scheduler = createGreetingScheduler({
    current,
    fetch: (key) => fetchGreeting((url) => apiFetch(url), key),
    play,
    activity,
  })
  watch(
    () => {
      const key = current()
      return key ? `${key.language}|${key.personaId}|${key.projectId}` : ''
    },
    () => void scheduler.sync(),
    { immediate: true },
  )
  return { reset: scheduler.reset, sync: scheduler.sync }
}
