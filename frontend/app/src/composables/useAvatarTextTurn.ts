/**
 * useAvatarTextTurn — text-mode turns for useAvatarChat over HTTP
 * POST /api/v1/chat (standard chat completions, any provider), including
 * turn revisions for merged re-sends and the /accept delivery acknowledgement.
 */
import type { Ref } from 'vue'
import { apiFetch } from '../api/http'
import { parseDecisionDebug, type DecisionDebug } from '../components/debug/decisionDebug'
import {
       CONNECT_TIMEOUT_MS,
       createClientId,
       type AvatarState,
       type ChatMessage,
       type ChatOptions,
       type ChatResponse,
       type UtteranceContext,
} from './avatarChatTypes'

export const DEFAULT_TEXT_CHAT_ENDPOINT = '/api/v1/chat'

export interface PendingTurn {
       text: string
       messageIndex: number
       turnId: string
       revision: number
}

interface TextTurnContext {
       options: ChatOptions
       state: Ref<AvatarState>
       messages: Ref<ChatMessage[]>
       sessionId: Ref<string | null>
       decisionDebugEnabled: Ref<boolean>
       decisionDebug: Ref<DecisionDebug | null>
       projectId: () => string
       personaId: () => string
       applyResponseMedia: (data: ChatResponse) => void
       playReply: (text: string, context: UtteranceContext) => void
}

export function useAvatarTextTurn(context: TextTurnContext) {
       const { options, state, messages, sessionId, decisionDebugEnabled, decisionDebug } = context
       // AbortController for in-flight text-mode fetch
       let textAbortController: AbortController | null = null
       let textRequestId = 0
       // 文字模式還在等回答的那一句。使用者這時再補一句，就跟它合併成一次重送，
       // 而不是只答後一句；messages 裡也只改那一則，不多一個氣泡。
       let awaitingReply: PendingTurn | null = null
       // 下一輪的歷史必須包含前台已接受的上一輪；停止播放不能撤銷這次確認。
       let acceptingReply: Promise<void> | null = null

       async function _sendMessageText(
              text: string,
              speechLanguage?: string | null,
              /** 合併重送時，改寫這一則使用者訊息而不是新增一則。 */
              mergedTurn?: PendingTurn,
       ): Promise<void> {
              const requestId = ++textRequestId
              const abort = new AbortController()
              textAbortController = abort
              const previousAcceptance = acceptingReply
              const turnId = mergedTurn?.turnId ?? createClientId()
              const revision = (mergedTurn?.revision ?? 0) + 1
              const requestSessionId = sessionId.value
              const requestProjectId = context.projectId()
              const requestPersonaId = context.personaId()

              const replaceMessageIndex = mergedTurn?.messageIndex
              const replaced = replaceMessageIndex === undefined ? undefined : messages.value[replaceMessageIndex]
              if (replaced) {
                     replaced.text = text
              } else {
                     messages.value.push({ role: 'user', text, timestamp: Date.now() })
              }
              awaitingReply = {
                     text,
                     turnId,
                     revision,
                     messageIndex: replaced && replaceMessageIndex !== undefined
                            ? replaceMessageIndex
                            : messages.value.length - 1,
              }
              state.value = 'THINKING'

              try {
                     if (previousAcceptance) await previousAcceptance.catch(() => {})
                     if (requestId !== textRequestId || abort.signal.aborted) return
                     const res = await apiFetch(options.chatEndpoint ?? DEFAULT_TEXT_CHAT_ENDPOINT, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', ...(options.requestHeaders?.() ?? {}) },
                            body: JSON.stringify({
                                   message: text,
                                   persona_id: requestPersonaId,
                                   project_id: requestProjectId,
                                   session_id: requestSessionId,
                                   turn_id: turnId,
                                   turn_revision: revision,
                                   mode: options.replyMode?.() ?? '',
                                   decision_debug: decisionDebugEnabled.value,
                                   ...(speechLanguage ? { metadata: { speech_language: speechLanguage } } : {}),
                            }),
                            signal: abort.signal,
                     })

                     if (requestId !== textRequestId || abort.signal.aborted) return
                     if (!res.ok) {
                            awaitingReply = null
                            const err = await res.json().catch(() => ({}))
                            const msg = (err as Record<string, string>).error ?? `HTTP ${res.status}`
                            options.onServerError?.('BRAIN_ERROR', msg)
                            state.value = 'ERROR'
                            return
                     }

                     const data = await res.json() as ChatResponse
                     if (requestId !== textRequestId || abort.signal.aborted) return
                     // 解析出完整回答才關閉合併視窗；headers 到了但 body 未到仍可補句。
                     awaitingReply = null
                     if (data.requires_accept) {
                            if (data.turn_id !== turnId || data.turn_revision !== revision) {
                                   throw new Error('回答的回合版本不符')
                            }
                            const acceptance = acceptReply({
                                   session_id: requestSessionId,
                                   project_id: requestProjectId,
                                   persona_id: requestPersonaId,
                                   turn_id: turnId,
                                   turn_revision: revision,
                            })
                            acceptingReply = acceptance
                            try {
                                   await acceptance
                            } finally {
                                   if (acceptingReply === acceptance) acceptingReply = null
                            }
                            if (requestId !== textRequestId || abort.signal.aborted) return
                     }
                     if (data.session_id) sessionId.value = data.session_id
                     if (decisionDebugEnabled.value) decisionDebug.value = parseDecisionDebug(data.decision_debug)
                     context.applyResponseMedia(data)
                     state.value = 'IDLE'
                     if (data.reply?.trim()) {
                            context.playReply(data.reply, {
                                   source: 'text',
                                   speechLanguage: speechLanguage ?? null,
                            })
                     }
              } catch (err) {
                     if ((err as Error).name !== 'AbortError' && requestId === textRequestId) {
                            console.error('[AvatarChat] text chat error:', err)
                            if (requestId === textRequestId) awaitingReply = null
                            state.value = 'ERROR'
                            options.onServerError?.('BRAIN_ERROR', (err as Error).message)
                     }
              } finally {
                     if (textAbortController === abort) {
                            textAbortController = null
                     }
              }
       }

       async function acceptReply(payload: Record<string, unknown>): Promise<void> {
              const endpoint = options.chatAcceptEndpoint
                     ?? `${options.chatEndpoint ?? DEFAULT_TEXT_CHAT_ENDPOINT}/accept`
              // 回應丟失時最多重試一次；伺服器確認具冪等性，不會多寫一輪。
              for (let attempt = 0; attempt < 2; attempt++) {
                     try {
                            const response = await apiFetch(endpoint, {
                                   method: 'POST',
                                   headers: { 'Content-Type': 'application/json', ...(options.requestHeaders?.() ?? {}) },
                                   body: JSON.stringify(payload),
                                   signal: AbortSignal.timeout(CONNECT_TIMEOUT_MS),
                            })
                            if (!response.ok) {
                                   if (response.status < 500) throw new Error(`確認回答失敗：HTTP ${response.status}`)
                                   if (attempt === 0) continue
                                   throw new Error(`確認回答失敗：HTTP ${response.status}`)
                            }
                            return
                     } catch (error) {
                            if (attempt === 1 || (error as Error).message.startsWith('確認回答失敗：HTTP 4')) throw error
                     }
              }
       }

       /** Drop the in-flight request so a late answer is neither accepted nor played. */
       function cancel(): void {
              textRequestId += 1
              textAbortController?.abort()
              textAbortController = null
       }

       return {
              send: _sendMessageText,
              cancel,
              pending: (): PendingTurn | null => awaitingReply,
              forgetPending: (): void => { awaitingReply = null },
              hasActiveRequest: (): boolean => Boolean(textAbortController),
       }
}
