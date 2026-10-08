export interface DecisionSignal {
  id: string
  type: 'noul' | 'choice'
  probability_true?: number | null
  resolved?: boolean | null
  value?: string | null
  confidence?: number | null
  accepted: boolean
}
export interface DecisionDebug {
  turn_id: string
  status: 'available' | 'fallback' | 'disabled'
  provider: string
  hop_id: string
  model: string
  elapsed_ms: number
  signals: readonly DecisionSignal[]
  policy: Record<string, string | boolean | readonly string[] | null>
  scope?: 'text' | 'audio_retrieval_only'
}
export const signalLabels: Record<string, string> = {
  needs_knowledge: '需要專案知識', needs_web: '需要網路資訊', needs_memory: '需要過去記憶',
  turn_intent: '對話意圖', dominant_language: '主要輸入語言',
  requested_response_language: '指定回覆語言', tone: '情緒／語氣',
  uses_zh: '使用中文', uses_en: '使用英文', uses_es: '使用西文', uses_nan: '使用台語',
  uses_ja: '使用日文', uses_ko: '使用韓文', uses_other: '使用其他語言',
}
const valueLabels: Record<string, string> = {
  neutral: '平穩', confused: '困惑', frustrated: '挫折／不耐煩', urgent: '急迫', lighthearted: '輕鬆',
  zh: '中文', en: '英文', es: '西文', nan: '台語', ja: '日文', ko: '韓文', other: '其他語言',
  none: '未指定', undetermined: '未確定', social: '寒暄／閒聊', task: '提問／任務',
  ambiguous: '意圖未明', follow_user: '依使用者指定',
}
export function labelValue(value: unknown): string {
  if (value === true) return '需要'
  if (value === false) return '不需要'
  if (Array.isArray(value)) return value.map(labelValue).join('、') || '未確定'
  if (typeof value === 'string') return valueLabels[value] ?? value
  return '沿用原本規則'
}
function probability(value: unknown): boolean {
  return value == null || (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1)
}
function owns(object: object, key: string): boolean { return Object.prototype.hasOwnProperty.call(object, key) }
export function parseDecisionDebug(value: unknown): DecisionDebug | null {
  if (!value || typeof value !== 'object') return null
  const data = value as DecisionDebug
  if (!['available', 'fallback', 'disabled'].includes(data.status)
    || !Array.isArray(data.signals) || data.signals.length > 14
    || !data.policy || typeof data.policy !== 'object' || Array.isArray(data.policy)
    || typeof data.turn_id !== 'string' || data.turn_id.length > 256
    || typeof data.provider !== 'string' || data.provider.length > 64
    || typeof data.hop_id !== 'string' || data.hop_id.length > 64
    || typeof data.model !== 'string' || data.model.length > 128
    || typeof data.elapsed_ms !== 'number' || !Number.isFinite(data.elapsed_ms) || data.elapsed_ms < 0) return null
  const signals: DecisionSignal[] = []
  for (const signal of data.signals) {
    if (!signal || typeof signal.id !== 'string' || !owns(signalLabels, signal.id)
      || !['noul', 'choice'].includes(signal.type) || typeof signal.accepted !== 'boolean'
      || !probability(signal.probability_true) || !probability(signal.confidence)
      || (signal.resolved != null && typeof signal.resolved !== 'boolean')
      || (signal.value != null && (typeof signal.value !== 'string' || !owns(valueLabels, signal.value)))) return null
    signals.push({ id: signal.id, type: signal.type, accepted: signal.accepted,
      value: signal.value, confidence: signal.confidence, probability_true: signal.probability_true, resolved: signal.resolved })
  }
  const policy: DecisionDebug['policy'] = {}
  for (const key of ['needs_knowledge','needs_web','needs_memory','mixed_languages','input_languages',
    'dominant_language','requested_response_language','retrieval_language','response_language','turn_intent','tone']) {
    const item = data.policy[key]
    if (item == null || typeof item === 'boolean' || (typeof item === 'string' && owns(valueLabels, item))) {
      policy[key] = item ?? null
    } else if (Array.isArray(item) && item.length <= 7 && item.every(code => typeof code === 'string' && owns(valueLabels, code))) {
      policy[key] = [...item]
    } else return null
  }
  return { turn_id: data.turn_id, status: data.status, provider: data.provider,
    hop_id: data.hop_id, model: data.model, elapsed_ms: data.elapsed_ms,
    signals, policy,
    scope: data.scope === 'audio_retrieval_only' ? data.scope : data.scope === 'text' ? 'text' : undefined }
}
