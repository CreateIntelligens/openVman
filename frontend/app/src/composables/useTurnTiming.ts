/**
 * useTurnTiming — 一輪對話從開始講話到虛擬人開口的各個時間點。
 *
 * 要量「整個流程多久」只能在前台量：講完話、開始播放都只發生在瀏覽器。每一輪
 * 播放開始（或被打斷、出錯）時送到後端，寫進 backend/logs/turn_timing.jsonl。
 * 時間用 performance.now()，不受系統校時影響；另外附第一個時間點的牆上時間，
 * 方便跟其他 log 對時間。
 */
import { apiFetch } from '../api/http'

export type TurnMark =
  | 'speech_start'
  | 'speech_end'
  | 'asr_done'
  | 'sent'
  | 'reply_done'
  | 'tts_start'
  | 'first_audio'
  | 'playback_start'

export type TurnOutcome = 'played' | 'interrupted' | 'error' | 'superseded'

export interface TurnContext {
  project_id: string
  session_id: string
  voice_mode: string
  asr_engine: string
  tts_provider: string
  tts_voice: string
}

interface Turn {
  id: string
  input: 'voice' | 'text'
  marks: Partial<Record<TurnMark, number>>
  replyChars: number
}

type Now = () => number

function newTurnId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function span(marks: Partial<Record<TurnMark, number>>, from: TurnMark, to: TurnMark): number | undefined {
  const start = marks[from]
  const end = marks[to]
  return start === undefined || end === undefined ? undefined : Math.round(end - start)
}

/** 分段：撈 log 的人直接看這幾個數字，不用自己減。 */
export function turnDurations(marks: Partial<Record<TurnMark, number>>): Record<string, number> {
  const origin = marks.speech_end ?? marks.sent
  const pairs: Array<[string, number | undefined]> = [
    ['speech', span(marks, 'speech_start', 'speech_end')],
    // 講完到辨識結果回來：上傳＋辨識。
    ['asr', span(marks, 'speech_end', 'asr_done')],
    // 辨識完到真的送出：要先建連線時會出現在這裡。
    ['send', span(marks, 'asr_done', 'sent')],
    ['brain', span(marks, 'sent', 'reply_done')],
    ['tts_first_audio', span(marks, 'tts_start', 'first_audio')],
    ['to_playback', span(marks, 'first_audio', 'playback_start')],
    // 使用者體感的等待：講完話（打字就是送出）到聽到聲音。
    ['total', origin === undefined || marks.playback_start === undefined
      ? undefined
      : Math.round(marks.playback_start - origin)],
  ]
  return Object.fromEntries(pairs.filter((pair): pair is [string, number] => pair[1] !== undefined))
}

export function useTurnTiming(options: {
  context: () => TurnContext
  now?: Now
  wallClock?: Now
  send?: (payload: Record<string, unknown>) => void
}) {
  const now = options.now ?? (() => performance.now())
  const wallClock = options.wallClock ?? (() => Date.now())
  const send = options.send ?? ((payload) => {
    void apiFetch('/api/v1/metrics/turn', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      // 送出時頁面可能正要關掉；量測失敗不影響對話，不等也不重試。
      keepalive: true,
    }).catch(() => {})
  })

  let turn: Turn | null = null
  let speech: { start?: number; end?: number; asrDone?: number } = {}

  function speechStarted(): void {
    speech = { start: now() }
  }

  function speechEnded(): void {
    speech = { ...speech, end: now() }
  }

  /** 語音辨識回來了；接著的 begin() 會算成語音輸入。 */
  function asrDone(): void {
    speech = { ...speech, asrDone: now() }
  }

  /** 使用者這一輪開始了（語音辨識完或打字送出）。上一輪還沒播就被取代。 */
  function begin(): void {
    if (turn) finish('superseded')
    const voice = speech.asrDone !== undefined
    const marks: Turn['marks'] = {}
    if (voice) {
      if (speech.start !== undefined) marks.speech_start = speech.start
      if (speech.end !== undefined) marks.speech_end = speech.end
      marks.asr_done = speech.asrDone
    }
    turn = { id: newTurnId(), input: voice ? 'voice' : 'text', marks, replyChars: 0 }
    speech = {}
  }

  /** 每個時間點只記第一次（例如 TTS 會有很多段聲音）。 */
  function mark(name: TurnMark): void {
    if (turn && turn.marks[name] === undefined) turn.marks[name] = now()
  }

  function replyText(text: string): void {
    if (turn) turn.replyChars = text.length
  }

  function finish(outcome: TurnOutcome): void {
    const current = turn
    turn = null
    if (!current) return
    const values = Object.values(current.marks)
    if (!values.length) return
    const origin = Math.min(...values)
    const marksMs = Object.fromEntries(
      Object.entries(current.marks).map(([name, at]) => [name, Math.round(at - origin)]),
    )
    send({
      turn_id: current.id,
      input: current.input,
      outcome,
      started_at: new Date(wallClock() - (now() - origin)).toISOString(),
      marks_ms: marksMs,
      durations_ms: turnDurations(current.marks),
      reply_chars: current.replyChars,
      ...options.context(),
    })
  }

  /**
   * 播放被停掉（插話、按停止）。伺服器的停止通知可能在新一輪送出後才到，所以只
   * 結束已經收到回覆的那一輪，不要把剛開始的新一輪記成被打斷。
   */
  function interrupted(): void {
    if (turn && (turn.marks.reply_done !== undefined || turn.marks.first_audio !== undefined)) {
      finish('interrupted')
    }
  }

  /** 開始播放：這一輪量完了。 */
  function playbackStarted(): void {
    if (!turn) return
    mark('playback_start')
    finish('played')
  }

  return {
    speechStarted, speechEnded, asrDone, begin, mark, replyText, finish, interrupted, playbackStarted,
  }
}
