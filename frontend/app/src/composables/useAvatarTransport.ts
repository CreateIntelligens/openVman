/**
 * useAvatarTransport — live-mode WebSocket lifecycle for useAvatarChat:
 * connect (resolved only by server_init_ack), connect timeout, exponential
 * reconnect with jitter, and raw event sending. In text mode connect() only
 * mints a session id because text turns go over HTTP.
 */
import type { Ref } from 'vue'
import {
       CONNECT_TIMEOUT_MS,
       createClientId,
       type AvatarState,
       type ChatOptions,
} from './avatarChatTypes'

const MAX_RECONNECT_ATTEMPTS = 6

interface TransportContext {
       options: ChatOptions
       state: Ref<AvatarState>
       sessionId: Ref<string | null>
       isTextMode: () => boolean
       /** Socket opened; the caller sends client_init. */
       onOpen: () => void
       onJsonMessage: (data: Record<string, unknown>) => void
       /** First thing done when the socket closes, before reconnect scheduling. */
       onClose: () => void
}

export function useAvatarTransport(context: TransportContext) {
       const { options, state, sessionId } = context
       let socket: WebSocket | null = null
       let reconnectTimer: ReturnType<typeof setTimeout> | null = null
       let connectTimer: ReturnType<typeof setTimeout> | null = null
       let connectPromise: Promise<void> | null = null
       let resolveConnect: (() => void) | null = null
       let rejectConnect: ((reason?: unknown) => void) | null = null
       let reconnectAttempt = 0
       let intentionalDisconnect = false
       let lastUrlOverride: string | undefined
       let clientId = createClientId()

       function connect(url?: string): Promise<void> {
              if (context.isTextMode()) {
                     sessionId.value = createClientId()
                     state.value = 'IDLE'
                     return Promise.resolve()
              }

              if (sessionId.value && socket?.readyState === WebSocket.OPEN) {
                     return Promise.resolve()
              }
              if (connectPromise) return connectPromise

              intentionalDisconnect = false
              connectPromise = new Promise((resolve, reject) => {
                     resolveConnect = resolve
                     rejectConnect = reject
                     const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
                     const host = window.location.host
                     clientId = createClientId()
                     const wsUrl = url ?? options.wsUrlBuilder?.(clientId) ?? `${protocol}://${host}/api/v1/ws/${clientId}`
                     lastUrlOverride = url

                     state.value = 'CONNECTING'
                     socket = new WebSocket(wsUrl)
                     socket.binaryType = 'arraybuffer'

                     socket.onopen = () => {
                            console.log('[AvatarChat] WebSocket connected')
                            context.onOpen()
                     }

                     socket.onmessage = (event) => {
                            if (typeof event.data === 'string') {
                                   context.onJsonMessage(JSON.parse(event.data))
                            } else {
                                   // Binary frame = PCM audio chunk
                                   options.onAudioChunk?.(event.data as ArrayBuffer)
                            }
                     }

                     socket.onclose = () => {
                            context.onClose()
                            console.log('[AvatarChat] WebSocket disconnected')
                            const disconnectError = new Error('WebSocket disconnected before initialization')
                            rejectPendingConnect(disconnectError)
                            socket = null
                            sessionId.value = null
                            state.value = 'DISCONNECTED'
                            options.onDisconnect?.()
                            if (intentionalDisconnect) return
                            if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
                                   state.value = 'ERROR'
                                   console.warn('[AvatarChat] reconnect attempts exhausted')
                                   options.onReconnectExhausted?.()
                                   return
                            }
                            state.value = 'RECONNECTING'
                            const baseDelay = Math.min(1000 * Math.pow(2, reconnectAttempt), 30000)
                            const delay = baseDelay * (0.75 + Math.random() * 0.5)
                            reconnectAttempt++
                            reconnectTimer = setTimeout(() => {
                                   void connect(url).catch(console.error)
                            }, delay)
                     }

                     socket.onerror = (err) => {
                            console.error('[AvatarChat] WebSocket error:', err)
                            state.value = 'ERROR'
                     }

                     connectTimer = setTimeout(() => {
                            rejectPendingConnect(new Error('WebSocket initialization timed out'))
                            socket?.close()
                     }, CONNECT_TIMEOUT_MS)
              })
              return connectPromise
       }

       /** server_init_ack 才算連上：重設重連次數並放行等待中的 connect()。 */
       function resolvePendingConnect(): void {
              reconnectAttempt = 0
              if (connectTimer) clearTimeout(connectTimer)
              connectTimer = null
              resolveConnect?.()
              connectPromise = null
              resolveConnect = null
              rejectConnect = null
       }

       function rejectPendingConnect(reason: unknown): void {
              if (connectTimer) clearTimeout(connectTimer)
              connectTimer = null
              rejectConnect?.(reason)
              connectPromise = null
              resolveConnect = null
              rejectConnect = null
       }

       function isOpen(): boolean {
              return socket !== null && socket.readyState === WebSocket.OPEN
       }

       function sendEvent(payload: Record<string, unknown>): void {
              sendRaw(JSON.stringify(payload))
       }

       function sendRaw(data: string): void {
              if (socket && socket.readyState === WebSocket.OPEN) {
                     socket.send(data)
              }
       }

       /** Close without triggering reconnect; the caller resets session state. */
       function close(): void {
              intentionalDisconnect = true
              if (reconnectTimer) clearTimeout(reconnectTimer)
              reconnectTimer = null
              rejectPendingConnect(new Error('Connection closed'))
              const activeSocket = socket
              socket = null
              if (activeSocket) {
                     activeSocket.onclose = null
                     activeSocket.close()
              }
       }

       function manualReconnect(disconnect: () => void): Promise<void> {
              const urlOverride = lastUrlOverride
              disconnect()
              reconnectAttempt = 0
              intentionalDisconnect = false
              return connect(urlOverride)
       }

       return {
              connect,
              resolvePendingConnect,
              isOpen,
              sendEvent,
              sendRaw,
              close,
              manualReconnect,
              clientId: () => clientId,
       }
}
