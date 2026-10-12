/**
 * Shared types, options and helpers for the avatar chat composables
 * (useAvatarChat, useAvatarTransport, useAvatarTextTurn, useAvatarVisualInput).
 */

export type AvatarState = 'DISCONNECTED' | 'CONNECTING' | 'RECONNECTING' | 'IDLE' | 'THINKING' | 'SPEAKING' | 'ERROR'
export type VisualSignalState = 'clear' | 'detecting' | 'locked'
export type VisualSignalColor = 'green' | 'yellow' | 'red'

export interface VisualState {
       event_key: string
       state: VisualSignalState
       color: VisualSignalColor
       label: string
       active: boolean
       true_streak: number
       confirm_frames: number
}

export interface ChatMessage {
       role: 'user' | 'ai'
       text: string
       timestamp: number
       sourcePath?: string
       sourcePathContent?: string
       imageId?: string
       url?: string
       projectId?: string
}

export interface ChatResponse {
       decision_debug?: unknown
       reply?: string
       session_id?: string
       citations?: unknown
       image_id?: unknown
       url?: unknown
       requires_accept?: boolean
       turn_id?: string
       turn_revision?: number
}

export interface SendMessageResult {
       accepted: boolean
       reason?: 'empty' | 'not_ready'
       /** 這句跟還在等回答的上一句合併重送了（同一輪，不是新的一輪）。 */
       merged?: boolean
}

export interface UtteranceContext {
       source: 'text' | 'visual' | 'live'
       speechLanguage: string | null
}

export interface ChatOptions {
       /** Called when a PCM audio chunk arrives (binary frame) */
       onAudioChunk?: (data: ArrayBuffer) => void
       /** Called when audio playback should stop */
       onStopAudio?: () => void
       /**
        * Called when an LLM utterance finishes (is_final=true on
        * server_stream_chunk). Receives the fully accumulated text for the
        * utterance — use this to drive a TTS synthesis pass.
        */
       onUtteranceComplete?: (text: string, context: UtteranceContext) => void
       /** Initial persona ID to use (default: "default") */
       personaId?: string
       /** Lip-sync mode to advertise after server_init_ack (default: "webgl") */
       lipSyncMode?: string
       /** Called on server_error with parsed error code, message and optional retry delay */
       onServerError?: (code: string, message: string, retryAfterMs?: number) => void
       /** Called when gateway_status event arrives */
       onGatewayStatus?: (plugin: string, status: string, message: string) => void
       /** Called whenever the WebSocket disconnects (before reconnect scheduling) */
       onDisconnect?: () => void
       /** Called after automatic reconnect attempts are exhausted */
       onReconnectExhausted?: () => void
       /** Chat mode: 'live' uses Gemini Live WS, 'text' uses HTTP /api/v1/chat */
       mode?: 'live' | 'text'
       /** Override text-mode chat endpoint. */
       chatEndpoint?: string
       /** Delivery acknowledgement for replaceable text turns. */
       chatAcceptEndpoint?: string
       /** Override text-mode vision describe endpoint. */
       visionEndpoint?: string
       /** Override text-mode vision reset endpoint. */
       visionResetEndpoint?: string
       /** Extra headers for text-mode requests. */
       requestHeaders?: () => Record<string, string>
       /** 每次送出時讀取的回覆深度（fast / standard / deep）。用 getter 而不是
        *  固定值，使用者在設定裡改完下一句就生效。 */
       replyMode?: () => string
       /** Override live-mode WebSocket URL creation. */
       wsUrlBuilder?: (clientId: string) => string
       /** Surface name sent in client_init capabilities. */
       surface?: string
       /** Project ID sent in client_init and text-mode requests. */
       projectId?: string
}

export const CONNECT_TIMEOUT_MS = 10000

export function createClientId(): string {
       if (crypto?.randomUUID) return crypto.randomUUID()

       if (crypto?.getRandomValues) {
              const bytes = new Uint8Array(16)
              crypto.getRandomValues(bytes)
              bytes[6] = (bytes[6] & 0x0f) | 0x40
              bytes[8] = (bytes[8] & 0x3f) | 0x80
              const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
              return [hex.slice(0,4), hex.slice(4,6), hex.slice(6,8), hex.slice(8,10), hex.slice(10,16)]
                     .map(g => g.join('')).join('-')
       }

       return `client-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function isRecord(value: unknown): value is Record<string, unknown> {
       return typeof value === 'object' && value !== null
}
