/**
 * useAvatarVisualInput — camera-frame input channel for useAvatarChat
 * (AI 的眼睛) and the visual signal state the backend reports back.
 *
 * 攝影機畫面是一條獨立的輸入管道：每秒一幀，由後端 VLM 轉成中性
 * 視覺描述餵給 AI。不推 user bubble、不翻 THINKING——AI 是否/如何
 * 反應完全自行決定。
 */
import type { Ref } from 'vue'
import { apiFetch } from '../api/http'
import {
       isRecord,
       type ChatOptions,
       type UtteranceContext,
       type VisualState,
} from './avatarChatTypes'

export const DEFAULT_VISION_ENDPOINT = '/api/v1/vision/describe'
export const DEFAULT_VISION_RESET_ENDPOINT = '/api/v1/vision/reset'

export const DEFAULT_VISUAL_STATE: VisualState = {
       event_key: 'person',
       state: 'clear',
       color: 'green',
       label: '無人',
       active: false,
       true_streak: 0,
       confirm_frames: 3,
}

function normalizeVisualState(value: unknown): VisualState | null {
       if (!isRecord(value)) return null
       const state = value.state
       const color = value.color
       if (state !== 'clear' && state !== 'detecting' && state !== 'locked') return null
       if (color !== 'green' && color !== 'yellow' && color !== 'red') return null

       return {
              event_key: typeof value.event_key === 'string' ? value.event_key : 'person',
              state,
              color,
              label: typeof value.label === 'string' ? value.label : DEFAULT_VISUAL_STATE.label,
              active: Boolean(value.active),
              true_streak: typeof value.true_streak === 'number' ? value.true_streak : 0,
              confirm_frames: typeof value.confirm_frames === 'number' ? value.confirm_frames : 3,
       }
}

interface VisualInputContext {
       options: ChatOptions
       visualState: Ref<VisualState>
       sessionId: Ref<string | null>
       isTextMode: () => boolean
       /** Live socket is open and the session is initialised. */
       isLiveReady: () => boolean
       sendEvent: (payload: Record<string, unknown>) => void
       projectId: () => string
       personaId: () => string
       playReply: (text: string, context: UtteranceContext) => void
}

export function useAvatarVisualInput(context: VisualInputContext) {
       const { options, visualState, sessionId } = context
       // 視覺管道每秒一幀；後端兩段 LLM 可能超過 1 秒。此旗標在前一幀
       // 仍在處理時丟棄新幀，避免堆疊請求（與後端 VLM busy 保護同精神）。
       let visionInFlight = false

       function resetVisualState(): void {
              visualState.value = { ...DEFAULT_VISUAL_STATE }
       }

       function applyVisualState(value: unknown): void {
              const next = normalizeVisualState(value)
              if (next) visualState.value = next
       }

       function sendVisualInput(
              frameBase64: string,
              mimeType: string,
              timestamp: number,
       ): void {
              if (context.isTextMode()) {
                     void _sendVisualInputText(frameBase64, mimeType, timestamp)
                     return
              }

              if (!context.isLiveReady()) return
              context.sendEvent({
                     event: 'client_video_frame',
                     frame_base64: frameBase64,
                     mime_type: mimeType,
                     timestamp,
              })
       }

       function canSendVisualInput(): boolean {
              if (context.isTextMode()) return !visionInFlight
              return context.isLiveReady()
       }

       async function _sendVisualInputText(
              frameBase64: string,
              mimeType: string,
              timestamp: number,
       ): Promise<void> {
              if (visionInFlight) return
              visionInFlight = true
              try {
                     const res = await apiFetch(options.visionEndpoint ?? DEFAULT_VISION_ENDPOINT, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', ...(options.requestHeaders?.() ?? {}) },
                            body: JSON.stringify({
                                   frame_base64: frameBase64,
                                   mime_type: mimeType,
                                   timestamp,
                                   persona_id: context.personaId(),
                                   project_id: context.projectId(),
                                   session_id: sessionId.value,
                            }),
                     })
                     if (!res.ok) return
                     const data = await res.json() as { reply?: string; session_id?: string; visual_state?: unknown }
                     if (data.session_id) sessionId.value = data.session_id
                     applyVisualState(data.visual_state)
                     if (data.reply?.trim()) {
                            context.playReply(data.reply, {
                                   source: 'visual',
                                   speechLanguage: null,
                            })
                     }
              } catch (err) {
                     // 視覺管道失敗靜默記 log，不打斷使用者
                     console.warn('[AvatarChat] vision describe failed:', err)
              } finally {
                     visionInFlight = false
              }
       }

       async function resetVisualInput(): Promise<void> {
              visionInFlight = false
              resetVisualState()
              if (context.isTextMode()) {
                     await _resetVisualInputText()
                     return
              }

              if (!context.isLiveReady()) return
              context.sendEvent({
                     event: 'client_camera_reset',
                     timestamp: Date.now(),
              })
       }

       async function _resetVisualInputText(): Promise<void> {
              if (!sessionId.value) return
              try {
                     const res = await apiFetch(options.visionResetEndpoint ?? DEFAULT_VISION_RESET_ENDPOINT, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', ...(options.requestHeaders?.() ?? {}) },
                            body: JSON.stringify({ session_id: sessionId.value }),
                     })
                     if (!res.ok) return
                     const data = await res.json() as { visual_state?: unknown }
                     applyVisualState(data.visual_state)
              } catch (err) {
                     console.warn('[AvatarChat] vision reset failed:', err)
              }
       }

       return {
              resetVisualState,
              applyVisualState,
              sendVisualInput,
              canSendVisualInput,
              resetVisualInput,
       }
}
