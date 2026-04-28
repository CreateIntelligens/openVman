/**
 * useAvatarChat — Vue 3 composable for WebSocket communication
 * with the openVman backend gateway.
 *
 * Protocol:
 *   client_init → server_init_ack
 *   user_speak  → server_stream_chunk (audio) → server_stop_audio
 *   client_interrupt
 */
import { ref, readonly, onUnmounted } from 'vue'

export type AvatarState = 'DISCONNECTED' | 'CONNECTING' | 'IDLE' | 'THINKING' | 'SPEAKING' | 'ERROR'

export interface ChatMessage {
       role: 'user' | 'ai'
       text: string
       timestamp: number
}

interface ChatOptions {
       /** Called when a PCM audio chunk arrives (binary frame) */
       onAudioChunk?: (data: ArrayBuffer) => void
       /** Called when audio playback should stop */
       onStopAudio?: () => void
       /**
        * Called when an LLM utterance finishes (is_final=true on
        * server_stream_chunk). Receives the fully accumulated text for the
        * utterance — use this to drive a TTS synthesis pass.
        */
       onUtteranceComplete?: (text: string) => void
}

function createClientId(): string {
       if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
              return crypto.randomUUID()
       }

       if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
              const bytes = new Uint8Array(16)
              crypto.getRandomValues(bytes)
              bytes[6] = (bytes[6] & 0x0f) | 0x40
              bytes[8] = (bytes[8] & 0x3f) | 0x80
              const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0'))
              return [
                     hex.slice(0, 4).join(''),
                     hex.slice(4, 6).join(''),
                     hex.slice(6, 8).join(''),
                     hex.slice(8, 10).join(''),
                     hex.slice(10, 16).join(''),
              ].join('-')
       }

       return `client-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useAvatarChat(options: ChatOptions = {}) {
       const state = ref<AvatarState>('DISCONNECTED')
       const messages = ref<ChatMessage[]>([])
       const sessionId = ref<string | null>(null)

       let socket: WebSocket | null = null
       let reconnectTimer: ReturnType<typeof setTimeout> | null = null
       // Buffer of text chunks for the in-flight LLM utterance. Flushed to
       // `onUtteranceComplete` when `is_final=true` arrives (or on interrupt).
       let utteranceBuffer = ''

       // ── Connect ────────────────────────────────────────────
       function connect(url?: string): Promise<void> {
              return new Promise((resolve, reject) => {
                     if (socket) {
                            if (socket.readyState === WebSocket.OPEN) {
                                   resolve()
                            } else {
                                   resolve() // Assuming it's already connecting, resolve so that caller can proceed (or could reject/await)
                            }
                            return
                     }

                     const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
                     const host = window.location.host
                     const clientId = createClientId()
                     const wsUrl = url ?? `${protocol}://${host}/ws/${clientId}`

                     state.value = 'CONNECTING'
                     socket = new WebSocket(wsUrl)
                     socket.binaryType = 'arraybuffer'

                     socket.onopen = () => {
                            console.log('[AvatarChat] WebSocket connected')
                            // Send client_init (openVman backend protocol)
                            sendEvent({
                                   event: 'client_init',
                                   client_id: clientId,
                                   protocol_version: '1.0.0',
                                   auth_token: 'openvman-admin',
                                   capabilities: {
                                          mode: 'gemini_live',
                                          project_id: 'default',
                                          surface: 'avatar',
                                          voice_source: 'custom'
                                   },
                                   timestamp: Date.now(),
                            })
                            resolve()
                     }

                     socket.onmessage = (event) => {
                            if (typeof event.data === 'string') {
                                   handleJsonMessage(JSON.parse(event.data))
                            } else {
                                   // Binary frame = PCM audio chunk
                                   options.onAudioChunk?.(event.data as ArrayBuffer)
                            }
                     }

                     socket.onclose = () => {
                            console.log('[AvatarChat] WebSocket disconnected')
                            socket = null
                            sessionId.value = null
                            state.value = 'DISCONNECTED'
                            // Auto-reconnect after 3s
                            reconnectTimer = setTimeout(() => { void connect(wsUrl).catch(console.error) }, 3000)
                     }

                     socket.onerror = (err) => {
                            console.error('[AvatarChat] WebSocket error:', err)
                            state.value = 'ERROR'
                            reject(err)
                     }
              })
       }

       // ── Handle incoming JSON events ────────────────────────
       function handleJsonMessage(data: Record<string, unknown>): void {
              const event = data.event as string | undefined

              switch (event) {
                     case 'server_init_ack':
                            sessionId.value = data.session_id as string
                            state.value = 'IDLE'
                            console.log(`[AvatarChat] Session: ${sessionId.value}`)
                            break

                     case 'server_stream_chunk': {
                            state.value = 'SPEAKING'
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
                                          options.onUtteranceComplete?.(full)
                                   }
                            }
                            break
                     }

                     case 'server_stop_audio':
                            options.onStopAudio?.()
                            state.value = 'IDLE'
                            break

                     case 'server_error':
                            console.error('[AvatarChat] Server error:', data.message)
                            state.value = 'ERROR'
                            break

                     case 'ping':
                            sendRaw(JSON.stringify({ event: 'pong', timestamp: Date.now() }))
                            break
              }
       }

       // ── Send user message ──────────────────────────────────
       function sendMessage(text: string): void {
              if (!socket || socket.readyState !== WebSocket.OPEN || !sessionId.value) return

              utteranceBuffer = ''
              messages.value.push({ role: 'user', text, timestamp: Date.now() })
              state.value = 'THINKING'
              sendEvent({
                     event: 'user_speak',
                     text,
                     timestamp: Date.now(),
              })
       }

       // ── Interrupt ──────────────────────────────────────────
       function interrupt(): void {
              utteranceBuffer = ''
              sendEvent({
                     event: 'client_interrupt',
                     partial_asr: '',
                     timestamp: Date.now(),
              })
              options.onStopAudio?.()
       }

       // ── Low-level send ─────────────────────────────────────
       function sendEvent(payload: Record<string, unknown>): void {
              sendRaw(JSON.stringify(payload))
       }

       function sendRaw(data: string): void {
              if (socket && socket.readyState === WebSocket.OPEN) {
                     socket.send(data)
              }
       }

       // ── Disconnect ─────────────────────────────────────────
       function disconnect(): void {
              if (reconnectTimer) clearTimeout(reconnectTimer)
              socket?.close()
              socket = null
              sessionId.value = null
              state.value = 'DISCONNECTED'
       }

       onUnmounted(() => {
              disconnect()
       })

       /** Create (or reuse) the active AI message bubble so appendAssistantText has a target. */
       function beginAssistantMessage(): void {
              const last = messages.value[messages.value.length - 1]
              if (last && last.role === 'ai' && last.text === '') return
              messages.value.push({ role: 'ai', text: '', timestamp: Date.now() })
       }

       /** Append a chunk of text to the current AI bubble (creating one if needed). */
       function appendAssistantText(chunk: string): void {
              if (!chunk) return
              const last = messages.value[messages.value.length - 1]
              if (last && last.role === 'ai') {
                     last.text += chunk
              } else {
                     messages.value.push({ role: 'ai', text: chunk, timestamp: Date.now() })
              }
       }

       return {
              state: readonly(state),
              messages,
              sessionId: readonly(sessionId),
              connect,
              disconnect,
              sendMessage,
              interrupt,
              beginAssistantMessage,
              appendAssistantText,
       }
}
