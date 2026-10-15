/**
 * chatSseStream — reads POST /api/v1/chat/stream (text/event-stream).
 *
 * Events: `sentence` {index, text}, `done` (same JSON as /chat), `error`
 * {status, detail}. Built on fetch + ReadableStream because EventSource
 * cannot send a POST body or custom headers.
 */

export interface SseEvent {
       event: string
       data: unknown
}

/** Parse one SSE block (text between blank lines). Returns null for comments / empty blocks. */
export function parseSseBlock(block: string): SseEvent | null {
       let event = 'message'
       const dataLines: string[] = []
       for (const rawLine of block.split('\n')) {
              const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
              if (!line || line.startsWith(':')) continue
              const colon = line.indexOf(':')
              const field = colon < 0 ? line : line.slice(0, colon)
              let value = colon < 0 ? '' : line.slice(colon + 1)
              if (value.startsWith(' ')) value = value.slice(1)
              if (field === 'event') event = value
              else if (field === 'data') dataLines.push(value)
       }
       if (!dataLines.length) return null
       const raw = dataLines.join('\n')
       let data: unknown = raw
       try {
              data = JSON.parse(raw)
       } catch {
              // 非 JSON 的 data 原樣交出去，由呼叫端決定要不要用。
       }
       return { event, data }
}

/** Yield SSE events in order as the response body arrives. */
export async function* readSseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
       const reader = body.getReader()
       const decoder = new TextDecoder()
       let buffer = ''
       try {
              for (;;) {
                     const { value, done } = await reader.read()
                     buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
                     buffer = buffer.replace(/\r\n/g, '\n')
                     let cut: number
                     while ((cut = buffer.indexOf('\n\n')) >= 0) {
                            const parsed = parseSseBlock(buffer.slice(0, cut))
                            buffer = buffer.slice(cut + 2)
                            if (parsed) yield parsed
                     }
                     if (done) break
              }
              const tail = parseSseBlock(buffer)
              if (tail) yield tail
       } finally {
              reader.releaseLock()
       }
}
