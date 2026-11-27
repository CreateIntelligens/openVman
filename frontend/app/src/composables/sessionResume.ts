/**
 * 畫面卡住而重新載入時，沿用原本那段對話。
 *
 * 只存在這個分頁的 sessionStorage（對話 id 原本就在這個瀏覽器裡，不會給到別處），
 * 載入後取一次就刪掉；超過 10 分鐘，或帳號、專案、角色跟重新載入前不同，就開新對話。
 * 綁帳號是因為登入過期時同一個分頁可能換人登入，不能讓下一個人接到前一個人的上下文。
 */
const RESUME_KEY = 'openvman.avatar.resume_session'
export const RESUME_WINDOW_MS = 10 * 60 * 1000

interface SavedConversation {
  conversationId: string
  userId: string
  projectId: string
  personaId: string
  savedAt: number
}

type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem' | 'removeItem'>

function sessionStore(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null
  } catch {
    return null
  }
}

export function saveResumeSession(
  conversation: Omit<SavedConversation, 'savedAt'>,
  { now = Date.now, storage = sessionStore() }: { now?: () => number; storage?: Storage | null } = {},
): void {
  if (!conversation.conversationId || !conversation.userId || !storage) return
  try {
    storage.setItem(RESUME_KEY, JSON.stringify({ ...conversation, savedAt: now() }))
  } catch {
    // 存不下就照舊開新對話。
  }
}

export function takeResumeSession(
  userId: string,
  projectId: string,
  personaId: string,
  { now = Date.now, storage = sessionStore() }: { now?: () => number; storage?: Storage | null } = {},
): string | null {
  if (!storage) return null
  try {
    const raw = storage.getItem(RESUME_KEY)
    storage.removeItem(RESUME_KEY)
    if (!raw) return null
    const saved = JSON.parse(raw) as Partial<SavedConversation>
    const age = now() - Number(saved.savedAt)
    if (typeof saved.conversationId !== 'string' || !saved.conversationId) return null
    if (!(age >= 0 && age <= RESUME_WINDOW_MS)) return null
    if (!userId || saved.userId !== userId) return null
    if (saved.projectId !== projectId || saved.personaId !== personaId) return null
    return saved.conversationId
  } catch {
    return null
  }
}

export function clearResumeSession(storage: Storage | null = sessionStore()): void {
  try {
    storage?.removeItem(RESUME_KEY)
  } catch {
    // 清不掉也只會在 10 分鐘內、同帳號同專案時被用到。
  }
}
