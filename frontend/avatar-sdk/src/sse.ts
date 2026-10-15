/**
 * Reads a `text/event-stream` response body (POST /api/v1/chat/stream).
 * Built on fetch + ReadableStream because EventSource cannot send a POST body
 * or custom headers.
 */

export interface SseEvent {
  data: unknown;
  event: string;
}

/** Parse one SSE block (text between blank lines); null for comments or empty blocks. */
function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  try {
    return { data: JSON.parse(raw), event };
  } catch {
    return { data: raw, event };
  }
}

/** Yield SSE events in order as the response body arrives. */
export async function* readSseEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let cut: number;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const parsed = parseSseBlock(buffer.slice(0, cut));
        buffer = buffer.slice(cut + 2);
        if (parsed) yield parsed;
      }
      if (done) break;
    }
    const tail = parseSseBlock(buffer);
    if (tail) yield tail;
  } finally {
    // 提早離開（done 之後 break、或中斷）時要放掉連線，不能留著讀。
    void reader.cancel().catch(() => undefined);
  }
}
