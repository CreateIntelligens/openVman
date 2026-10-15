/**
 * useAvatarChat — Vue 3 composable for chat with the openVman backend
 * gateway: messages, turn state, decision debug and live protocol events.
 * Transport and side channels live in sibling modules:
 *   useAvatarTransport   — live-mode WebSocket connect / reconnect
 *   useAvatarTextTurn    — text-mode HTTP turns (/api/v1/chat/stream or /api/v1/chat)
 *   useAvatarVisualInput — camera frames and visual signal state
 *
 * Protocol (live mode):
 *   client_init → server_init_ack
 *   user_speak  → server_stream_chunk (audio) → server_stop_audio
 *   client_interrupt
 *
 * Text mode: uses /api/v1/chat/stream when chatStreamEndpoint is set (sentences
 * reach TTS as they are written), otherwise /api/v1/chat.
 */
import { ref, readonly, onUnmounted } from 'vue'
import { parseDecisionDebug, type DecisionDebug } from '../components/debug/decisionDebug'
import {
       createClientId,
       isRecord,
       type AvatarState,
       type ChatMessage,
       type ChatOptions,
       type ChatResponse,
       type SendMessageResult,
       type UtteranceContext,
       type VisualState,
} from './avatarChatTypes'
import { useAvatarTextTurn } from './useAvatarTextTurn'
import { useAvatarTransport } from './useAvatarTransport'
import { DEFAULT_VISUAL_STATE, useAvatarVisualInput } from './useAvatarVisualInput'

export type {
       AvatarState,
       ChatMessage,
       SendMessageResult,
       UtteranceContext,
       VisualSignalColor,
       VisualSignalState,
       VisualState,
} from './avatarChatTypes'
export { DEFAULT_TEXT_CHAT_ENDPOINT, DEFAULT_TEXT_CHAT_STREAM_ENDPOINT } from './useAvatarTextTurn'
export { DEFAULT_VISION_ENDPOINT, DEFAULT_VISION_RESET_ENDPOINT } from './useAvatarVisualInput'

interface Citation {
       image_id?: unknown
       image?: unknown
       url?: unknown
       source_url?: unknown
}

export function useAvatarChat(options: ChatOptions = {}) {
       const state = ref<AvatarState>('DISCONNECTED')
       const messages = ref<ChatMessage[]>([])
       const decisionDebugEnabled = ref(false)
       const decisionDebug = ref<DecisionDebug | null>(null)
       let pendingDecisionClientTurn: string | null = null
       let pendingDecisionServerTurn: string | null = null
       const sessionId = ref<string | null>(null)
       const visualState = ref<VisualState>({ ...DEFAULT_VISUAL_STATE })
       let activeSourcePath: string | undefined = undefined
       let activeSourcePathContent: string | undefined = undefined
       let activeImageId: string | undefined = undefined
       let activeUrl: string | undefined = undefined

       let currentPersonaId = options.personaId ?? 'default'
       let currentProjectId = options.projectId ?? 'default'
       const surface = options.surface ?? 'avatar'
       const currentLipSyncMode = options.lipSyncMode ?? 'webgl'
       let currentMode: 'live' | 'text' = options.mode ?? 'live'
       // Buffer of text chunks for the in-flight LLM utterance. Flushed to
       // `onUtteranceComplete` when `is_final=true` arrives (or on interrupt).
       let utteranceBuffer = ''
       let liveSpeechLanguage: string | null = null
       let responsePlaybackActive = false

       const transport = useAvatarTransport({
              options,
              state,
              sessionId,
              isTextMode: () => currentMode === 'text',
              onOpen: () => sendEvent(_buildClientInit()),
              onJsonMessage: handleJsonMessage,
              onClose: clearDecisionDebug,
       })
       const { connect, sendEvent } = transport
       const textTurn = useAvatarTextTurn({
              options,
              state,
              messages,
              sessionId,
              decisionDebugEnabled,
              decisionDebug,
              projectId: () => currentProjectId,
              personaId: () => currentPersonaId,
              applyResponseMedia,
              attachStreamedMedia,
              playReply,
              replyStarted: (context) => {
                     responsePlaybackActive = true
                     options.onReplyStart?.(context)
              },
              replySentence: (text) => options.onReplySentence?.(text),
              replyFinished: (text) => options.onReplyEnd?.(text),
              abandonReply: () => {
                     responsePlaybackActive = false
                     options.onStopAudio?.()
              },
       })
       const {
              resetVisualState,
              applyVisualState,
              sendVisualInput,
              canSendVisualInput,
              resetVisualInput,
       } = useAvatarVisualInput({
              options,
              visualState,
              sessionId,
              isTextMode: () => currentMode === 'text',
              isLiveReady,
              sendEvent,
              projectId: () => currentProjectId,
              personaId: () => currentPersonaId,
              playReply,
       })

       function isLiveReady(): boolean {
              return Boolean(transport.isOpen() && sessionId.value)
       }

       function playReply(text: string, context: UtteranceContext): void {
              responsePlaybackActive = true
              options.onUtteranceComplete?.(text, context)
       }

       function optionalString(value: unknown): string | undefined {
              return typeof value === 'string' && value.trim() ? value.trim() : undefined
       }

       function applyResponseMedia(data: ChatResponse): void {
              const citations = Array.isArray(data.citations) ? data.citations : []
              const primary = isRecord(citations[0]) ? citations[0] as Citation : undefined
              const imageId = optionalString(data.image_id)
                     ?? optionalString(primary?.image_id)
                     ?? optionalString(primary?.image)
              const url = optionalString(data.url)
                     ?? optionalString(primary?.url)
                     ?? optionalString(primary?.source_url)
              if (imageId) activeImageId = imageId
              if (url) activeUrl = url
       }

       /** 串流回答的字幕氣泡通常在 done 之前就出現了，附圖要補到那個氣泡上。 */
       function attachStreamedMedia(data: ChatResponse, userMessageIndex: number): void {
              applyResponseMedia(data)
              const lastIndex = messages.value.length - 1
              const last = messages.value[lastIndex]
              if (last?.role === 'ai' && lastIndex > userMessageIndex) {
                     Object.assign(last, consumeActiveMetadata())
              }
       }

       function consumeActiveMetadata(): Pick<
              ChatMessage,
              'sourcePath' | 'sourcePathContent' | 'imageId' | 'url' | 'projectId'
       > {
              const source: Pick<
                     ChatMessage,
                     'sourcePath' | 'sourcePathContent' | 'imageId' | 'url' | 'projectId'
              > = {}
              if (activeSourcePath) source.sourcePath = activeSourcePath
              if (activeSourcePathContent) source.sourcePathContent = activeSourcePathContent
              if (activeImageId) {
                     source.imageId = activeImageId
                     source.projectId = currentProjectId
              }
              if (activeUrl) source.url = activeUrl
              activeSourcePath = undefined
              activeSourcePathContent = undefined
              activeImageId = undefined
              activeUrl = undefined
              return source
       }

       // ── Build client_init payload ──────────────────────────
       function _buildClientInit(): Record<string, unknown> {
              return {
                     event: 'client_init',
                     client_id: transport.clientId(),
                     protocol_version: '1.0.0',
                     capabilities: {
                            mode: 'gemini_live',
                            project_id: currentProjectId,
                            surface,
                            voice_source: 'custom',
                            persona_id: currentPersonaId,
                     },
                     timestamp: Date.now(),
              }
       }

       // ── Reinitialize with a new persona (safe when IDLE/DISCONNECTED) ──
       function reinit(personaId: string): void {
              clearDecisionDebug()
              currentPersonaId = personaId
              sendEvent(_buildClientInit())
       }

       function clearDecisionDebug(): void {
              decisionDebug.value = null
              pendingDecisionClientTurn = null
              pendingDecisionServerTurn = null
       }

       function setDecisionDebug(enabled: boolean): void {
              decisionDebugEnabled.value = enabled
              clearDecisionDebug()
              sendEvent({ event: 'set_decision_debug', enabled })
       }

       function setProject(projectId: string): void {
              clearDecisionDebug()
              currentProjectId = projectId
       }

       function setPersona(personaId: string): void {
              clearDecisionDebug()
              currentPersonaId = personaId
       }

       // ── Handle incoming JSON events ────────────────────────
       function handleJsonMessage(data: Record<string, unknown>): void {
              const event = data.event as string | undefined

              switch (event) {
                     case 'server_init_ack':
                            sessionId.value = data.session_id as string
                            state.value = 'IDLE'
                            transport.resolvePendingConnect()
                            console.log(`[AvatarChat] Session: ${sessionId.value}`)
                            sendEvent({ event: 'set_lip_sync_mode', mode: currentLipSyncMode })
                            sendEvent({ event: 'set_decision_debug', enabled: decisionDebugEnabled.value })
                            break

                     case 'server_stream_chunk': {
                            state.value = 'SPEAKING'
                            responsePlaybackActive = true
                            if (data.audio_base64) {
                                   const bin = atob(data.audio_base64 as string)
                                   const bytes = new Uint8Array(bin.length)
                                   for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
                                   options.onAudioChunk?.(bytes.buffer)
                            }
                            if (data.text) {
                                   utteranceBuffer += String(data.text)
                            }
                            if (data.is_final) {
                                   const full = utteranceBuffer
                                   utteranceBuffer = ''
                                   if (full.trim()) {
                                          options.onUtteranceComplete?.(full, {
                                                 source: 'live',
                                                 speechLanguage: liveSpeechLanguage,
                                          })
                                   }
                            }
                            break
                     }

                     case 'server_decision_debug':
                            if (decisionDebugEnabled.value && data.session_id === sessionId.value) {
                                   const report = parseDecisionDebug({ ...(data.diagnostics as object), scope: data.scope })
                                   const matchesTurn = report && (
                                          report.scope === 'text'
                                                 ? pendingDecisionClientTurn !== null && data.client_turn_id === pendingDecisionClientTurn
                                                 : pendingDecisionServerTurn !== null && report.turn_id === pendingDecisionServerTurn
                                   )
                                   if (matchesTurn) decisionDebug.value = report
                            }
                            break

                     case 'user_transcription':
                            clearDecisionDebug()
                            if (currentMode === 'live' && typeof data.decision_turn_id === 'string') {
                                   pendingDecisionServerTurn = data.decision_turn_id
                            }
                            break

                     case 'server_search_results':
                            applyResponseMedia({ citations: data.citations })
                            break

                     case 'server_stop_audio':
                            options.onStopAudio?.()
                            responsePlaybackActive = false
                            state.value = 'IDLE'
                            break

                     case 'server_error': {
                            const code = (data.error_code ?? 'UNKNOWN') as string
                            const msg = (data.message ?? '') as string
                            const retryAfterMs = data.retry_after_ms as number | undefined
                            console.error('[AvatarChat] Server error:', code, msg)
                            if (code !== 'SESSION_EXPIRED') state.value = 'ERROR'
                            options.onServerError?.(code, msg, retryAfterMs)
                            break
                     }

                     case 'gateway_status': {
                            const plugin = (data.plugin ?? '') as string
                            const gStatus = (data.status ?? '') as string
                            const gMsg = (data.message ?? '') as string
                            console.log(`[AvatarChat] gateway_status: ${plugin} → ${gStatus}`)
                            options.onGatewayStatus?.(plugin, gStatus, gMsg)
                            break
                     }

                     case 'server_camera_frame_status':
                            applyVisualState(data.visual_state)
                            break

                     case 'ping':
                            transport.sendRaw(JSON.stringify({ event: 'pong', timestamp: Date.now() }))
                            break
              }
       }

       /** 回答還沒出來（還沒有任何字）而且兩句都是使用者自己講的，才合併。
        *  快速問答帶著出處，跟別的話接在一起出處就不對了，所以不合併。 */
       function mergeTarget(sourcePath?: string): ReturnType<typeof textTurn.pending> {
              if (currentMode !== 'text' || state.value !== 'THINKING' || sourcePath) return null
              const awaitingReply = textTurn.pending()
              if (!awaitingReply || activeSourcePath) return null
              return messages.value[awaitingReply.messageIndex]?.role === 'user' ? awaitingReply : null
       }

       // ── Send user message ──────────────────────────────────
       function sendMessage(
              text: string,
              sourcePath?: string,
              sourcePathContent?: string,
              /** ASR 聽出的語言（例如台語 "nan"）；轉錄文字看不出來，要一起送給 Brain 記錄。 */
              speechLanguage?: string | null,
       ): SendMessageResult {
              const trimmed = text.trim()
              if (!trimmed) return { accepted: false, reason: 'empty' }

              if (currentMode === 'live' && !isLiveReady()) {
                     return { accepted: false, reason: 'not_ready' }
              }

              clearDecisionDebug()
              const merge = mergeTarget(sourcePath)
              stopActiveResponse()
              activeSourcePath = sourcePath
              activeSourcePathContent = sourcePathContent
              activeImageId = undefined
              activeUrl = undefined
              if (currentMode === 'text') {
                     if (merge) {
                            // 語言以後一句為準：兩句不同語言時，最後講的那句通常才是使用者要的回答語言。
                            void textTurn.send(`${merge.text}\n${trimmed}`, speechLanguage, merge)
                            return { accepted: true, merged: true }
                     }
                     void textTurn.send(trimmed, speechLanguage)
                     return { accepted: true }
              }

              liveSpeechLanguage = speechLanguage ?? null
              messages.value.push({ role: 'user', text: trimmed, timestamp: Date.now() })
              state.value = 'THINKING'
              pendingDecisionClientTurn = createClientId()
              sendEvent({
                     event: 'user_speak',
                     turn_id: pendingDecisionClientTurn,
                     text: trimmed,
                     timestamp: Date.now(),
                     ...(speechLanguage ? { speech_language: speechLanguage } : {}),
              })
              return { accepted: true }
       }

       // ── Interrupt ──────────────────────────────────────────
       function interrupt(): void {
              clearDecisionDebug()
              stopActiveResponse()
              state.value = 'IDLE'
       }

       function stopActiveResponse(): void {
              const shouldStopLocal =
                     responsePlaybackActive
                     || textTurn.hasActiveRequest()
                     || state.value === 'THINKING'
                     || state.value === 'SPEAKING'
                     || utteranceBuffer.length > 0

              utteranceBuffer = ''
              liveSpeechLanguage = null
              responsePlaybackActive = false
              textTurn.forgetPending()
              if (shouldStopLocal) options.onStopAudio?.()

              if (currentMode === 'text') {
                     textTurn.cancel()
                     return
              }

              if (isLiveReady() && (state.value === 'THINKING' || state.value === 'SPEAKING')) {
                     sendEvent({
                            event: 'client_interrupt',
                            partial_asr: '',
                            timestamp: Date.now(),
                     })
              }
       }

       // ── Disconnect ─────────────────────────────────────────
       function disconnect(): void {
              clearDecisionDebug()
              textTurn.cancel()
              textTurn.forgetPending()
              transport.close()
              sessionId.value = null
              resetVisualState()
              state.value = 'DISCONNECTED'
       }

       function setMode(mode: 'live' | 'text'): void {
              clearDecisionDebug()
              currentMode = mode
       }

       function manualReconnect(): Promise<void> {
              return transport.manualReconnect(disconnect)
       }

       onUnmounted(() => {
              disconnect()
       })

       /** Create (or reuse) the active AI message bubble so appendAssistantText has a target. */
       function beginAssistantMessage(): void {
              const last = messages.value[messages.value.length - 1]
              if (last && last.role === 'ai' && last.text === '') {
                     Object.assign(last, consumeActiveMetadata())
                     return
              }
              messages.value.push({
                     role: 'ai',
                     text: '',
                     timestamp: Date.now(),
                     ...consumeActiveMetadata(),
              })
       }

       /** Replace the current AI bubble's text (the streamed sentences differed from the final reply). */
       function setAssistantText(text: string): void {
              const last = messages.value[messages.value.length - 1]
              if (last && last.role === 'ai') last.text = text
              else appendAssistantText(text)
       }

       /** Append a chunk of text to the current AI bubble (creating one if needed). */
       function appendAssistantText(chunk: string): void {
              if (!chunk) return
              const last = messages.value[messages.value.length - 1]
              if (last && last.role === 'ai') {
                     last.text += chunk
              } else {
                     messages.value.push({
                            role: 'ai',
                            text: chunk,
                            timestamp: Date.now(),
                            ...consumeActiveMetadata(),
                     })
              }
       }

       return {
              state: readonly(state),
              messages,
              sessionId: readonly(sessionId),
              visualState: readonly(visualState),
              decisionDebug: readonly(decisionDebug),
              decisionDebugEnabled: readonly(decisionDebugEnabled),
              setDecisionDebug,
              clearDecisionDebug,
              connect,
              disconnect,
              sendMessage,
              mergesWithPending: (sourcePath?: string) => mergeTarget(sourcePath) !== null,
              sendVisualInput,
              canSendVisualInput,
              resetVisualInput,
              interrupt,
              reinit,
              setMode,
              setProject,
              setPersona,
              manualReconnect,
              beginAssistantMessage,
              appendAssistantText,
              setAssistantText,
       }
}
