import { OpenVmanAvatarError } from "./errors";
import { readSseEvents } from "./sse";
import type { OpenVmanAvatarOptions } from "./types";

interface ChatResponseBody {
  reply?: unknown;
  trace_id?: unknown;
}

export interface ReplyDetails {
  sessionId: string;
  traceId: string;
}

interface StreamErrorBody {
  detail?: unknown;
  status?: unknown;
}

type ConversationFailureCode = "CHAT_FAILED" | "SPEECH_FAILED";

export interface AvatarConversationDeps {
  interrupt(): void;
  onReply(text: string, details: ReplyDetails): void;
  onSentence(index: number, text: string): void;
  playAudio(source: ArrayBuffer): Promise<void>;
  pushPcm(chunk: Int16Array): Promise<void>;
  untilIdle(): Promise<void>;
}

/** Thrown when the stream route is missing on this deployment. */
class StreamRouteMissing extends Error {}

export class AvatarConversation {
  private sessionId: string | null = null;
  private turn: AbortController | null = null;
  private streamRouteMissing = false;
  private speechStreamMissing = false;

  constructor(
    private readonly resourceBaseUrl: string,
    private readonly options: OpenVmanAvatarOptions,
    private readonly deps: AvatarConversationDeps,
  ) {}

  async ask(text: string): Promise<string> {
    // 新的一輪必須先掐掉上一輪的串流與還在播的語音，避免兩段答案疊在一起。
    this.interrupt();
    const turn = new AbortController();
    this.turn = turn;
    try {
      if (!this.streamRouteMissing) {
        try {
          return await this.askStreaming(text, turn.signal);
        } catch (error) {
          if (!(error instanceof StreamRouteMissing)) throw error;
        }
      }
      const reply = await this.askWhole(text, turn.signal);
      // /chat 能用而串流路由不存在，代表這個部署還沒有串流，之後都直接走 /chat。
      if (!turn.signal.aborted) this.streamRouteMissing = true;
      return reply;
    } finally {
      if (this.turn === turn) this.turn = null;
    }
  }

  interrupt(): void {
    this.turn?.abort();
    this.turn = null;
    this.deps.interrupt();
  }

  private async askWhole(text: string, signal: AbortSignal): Promise<string> {
    const response = await this.send(
      `${this.resourceBaseUrl}/api/v1/chat`,
      this.chatPayload(text),
      "CHAT_FAILED",
      signal,
    );
    if (!response) return "";

    let body: ChatResponseBody;
    try {
      body = (await response.json()) as ChatResponseBody;
    } catch (error) {
      if (signal.aborted) return "";
      throw new OpenVmanAvatarError("CHAT_FAILED", errorMessage(error));
    }
    const reply = requireReply(body);
    if (signal.aborted) return reply;
    this.deps.onReply(reply, this.replyDetails(body));
    const audio = await this.requestSpeech(reply, signal);
    if (audio) await this.deps.playAudio(audio);
    return reply;
  }

  private async askStreaming(
    text: string,
    signal: AbortSignal,
  ): Promise<string> {
    const response = await this.send(
      `${this.resourceBaseUrl}/api/v1/chat/stream`,
      this.chatPayload(text),
      "CHAT_FAILED",
      signal,
      [404, 405],
    );
    if (!response) return "";
    if (response.status === 404 || response.status === 405) {
      throw new StreamRouteMissing();
    }
    if (!response.body) {
      throw new OpenVmanAvatarError(
        "CHAT_FAILED",
        "Chat stream response has no body.",
      );
    }

    const sentences: string[] = [];
    let reply: string | null = null;
    let doneBody: ChatResponseBody | null = null;
    try {
      for await (const { event, data } of readSseEvents(response.body)) {
        if (signal.aborted) break;
        if (event === "sentence") {
          const sentence = sentenceText(data);
          if (!sentence) continue;
          this.deps.onSentence(sentences.length, sentence);
          sentences.push(sentence);
        } else if (event === "done") {
          doneBody = data as ChatResponseBody;
          reply = requireReply(doneBody);
          break;
        } else if (event === "error") {
          throw streamError(data as StreamErrorBody);
        }
      }
    } catch (error) {
      if (signal.aborted) return sentences.join("");
      throw error instanceof OpenVmanAvatarError
        ? error
        : new OpenVmanAvatarError("CHAT_FAILED", errorMessage(error));
    }
    if (signal.aborted) return sentences.join("");
    if (reply === null) {
      throw new OpenVmanAvatarError(
        "CHAT_FAILED",
        "Chat stream ended without a final reply.",
      );
    }

    this.deps.onReply(reply, this.replyDetails(doneBody));
    // 句子事件只拿來顯示；聲音等 done 用整段回答打一次 TTS。分句打會讓第二段
    // 要等第一段下載完才送，第一句短時中間就斷音，而且每段的語氣各自不同。
    // 唸 done.reply 而不是句子拼接：模型中途改寫時，收回的句子不在 reply 裡。
    await this.speak(reply, signal);
    return reply;
  }

  private chatPayload(text: string): Record<string, unknown> {
    return omitUndefined({
      message: text,
      persona_id: this.options.personaId,
      project_id: this.options.projectId,
      session_id: this.ensureSessionId(),
    });
  }

  /**
   * Speaks the reply and resolves once it has been heard. Streams 16 kHz PCM
   * so playback starts with the first chunk instead of after the whole reply
   * is synthesized; deployments without the stream route fall back to
   * /v1/audio/speech.
   */
  private async speak(text: string, signal: AbortSignal): Promise<void> {
    if (!this.speechStreamMissing) {
      const response = await this.send(
        `${this.resourceBaseUrl}/api/v1/tts/stream`,
        omitUndefined({
          ...this.speechOptions(),
          format: "pcm16k",
          text,
        }),
        "SPEECH_FAILED",
        signal,
        [404, 405],
      );
      if (!response) return;
      if (response.status === 404 || response.status === 405) {
        this.speechStreamMissing = true;
      } else {
        if (!response.body) {
          throw new OpenVmanAvatarError(
            "SPEECH_FAILED",
            "Speech stream response has no body.",
          );
        }
        await this.pumpPcm(response.body, signal);
        if (!signal.aborted) await this.deps.untilIdle();
        return;
      }
    }
    const audio = await this.requestSpeech(text, signal);
    if (audio) await this.deps.playAudio(audio);
  }

  private async pumpPcm(
    body: ReadableStream<Uint8Array>,
    signal: AbortSignal,
  ): Promise<void> {
    const reader = body.getReader();
    // 網路切包不保證落在樣本邊界，留下奇數的那個 byte 接到下一包。
    let carry: number | null = null;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done || signal.aborted) break;
        if (!value || value.length === 0) continue;
        const bytes: Uint8Array = carry === null ? value : prependByte(carry, value);
        const usable: number = bytes.length - (bytes.length % 2);
        carry = usable < bytes.length ? bytes[usable] : null;
        if (usable === 0) continue;
        await this.deps.pushPcm(littleEndianInt16(bytes, usable));
      }
    } catch (error) {
      if (signal.aborted) return;
      throw new OpenVmanAvatarError("SPEECH_FAILED", errorMessage(error));
    } finally {
      if (signal.aborted) void reader.cancel().catch(() => undefined);
    }
  }

  private speechOptions(): Record<string, unknown> {
    return {
      provider: this.options.tts?.provider,
      voice: this.options.tts?.voice,
      // 同源 session 沒有 embed key 綁定專案，要靠這裡帶專案才套得到專案的聲音與分流。
      project_id: this.options.projectId,
      language: this.options.tts?.language,
    };
  }

  private async requestSpeech(
    text: string,
    signal: AbortSignal,
  ): Promise<ArrayBuffer | null> {
    const response = await this.send(
      `${this.resourceBaseUrl}/v1/audio/speech`,
      omitUndefined({ ...this.speechOptions(), input: text }),
      "SPEECH_FAILED",
      signal,
    );
    if (!response) return null;
    try {
      return await response.arrayBuffer();
    } catch (error) {
      if (signal.aborted) return null;
      throw new OpenVmanAvatarError("SPEECH_FAILED", errorMessage(error));
    }
  }

  /** Returns null when the turn was interrupted before a response arrived. */
  private async send(
    url: string,
    payload: Record<string, unknown>,
    failureCode: ConversationFailureCode,
    signal: AbortSignal,
    passThroughStatuses: readonly number[] = [],
  ): Promise<Response | null> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.options.embedKey) headers["X-Embed-Key"] = this.options.embedKey;

    let response: Response;
    try {
      response = await fetch(url, {
        body: JSON.stringify(payload),
        // embed key 是跨站呼叫，帶 cookie 只會踩到 CORS；session 模式則相反。
        credentials: this.options.embedKey ? "omit" : "include",
        headers,
        method: "POST",
        signal,
      });
    } catch (error) {
      if (signal.aborted) return null;
      throw new OpenVmanAvatarError(failureCode, errorMessage(error));
    }
    if (signal.aborted) return null;

    if (!response.ok && !passThroughStatuses.includes(response.status)) {
      throw httpError(response.status, failureCode, retryAfterHeader(response));
    }
    return response;
  }

  private replyDetails(body: ChatResponseBody | null): ReplyDetails {
    const traceId = body?.trace_id;
    return {
      sessionId: this.sessionId ?? "",
      traceId: typeof traceId === "string" ? traceId : "",
    };
  }

  private ensureSessionId(): string {
    this.sessionId ??= createSessionId();
    return this.sessionId;
  }
}

function requireReply(body: ChatResponseBody | null | undefined): string {
  const reply = body?.reply;
  if (typeof reply !== "string" || reply.length === 0) {
    throw new OpenVmanAvatarError(
      "CHAT_FAILED",
      "Chat response did not contain a reply.",
    );
  }
  return reply;
}

function sentenceText(data: unknown): string {
  const text = (data as { text?: unknown } | null)?.text;
  return typeof text === "string" ? text : "";
}

// 串流開始後的錯誤以 error 事件回報，status 與 detail 就是 /chat 會回的 HTTP 錯誤。
function streamError(body: StreamErrorBody | null): OpenVmanAvatarError {
  const status = typeof body?.status === "number" ? body.status : 502;
  const retryAfterMs = (body?.detail as { retry_after_ms?: unknown } | null)
    ?.retry_after_ms;
  const retryAfter = typeof retryAfterMs === "number" && retryAfterMs >= 0
    ? Math.ceil(retryAfterMs / 1000)
    : undefined;
  return httpError(status, "CHAT_FAILED", retryAfter);
}

function httpError(
  status: number,
  failureCode: ConversationFailureCode,
  retryAfterSeconds?: number,
): OpenVmanAvatarError {
  if (status === 401 || status === 403) {
    return new OpenVmanAvatarError(
      "UNAUTHORIZED",
      `Request rejected with HTTP ${status}.`,
    );
  }
  if (status === 429) {
    return new OpenVmanAvatarError(
      "RATE_LIMITED",
      "Request rejected with HTTP 429.",
      retryAfterSeconds,
    );
  }
  return new OpenVmanAvatarError(
    failureCode,
    `Request failed with HTTP ${status}.`,
  );
}

function retryAfterHeader(response: Response): number | undefined {
  const header = response.headers?.get?.("Retry-After");
  if (!header) return undefined;
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

function omitUndefined(
  payload: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  );
}

function createSessionId(): string {
  const cryptoApi = (globalThis as {
    crypto?: { randomUUID?: () => string };
  }).crypto;
  if (typeof cryptoApi?.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }
  // 非安全 context 或舊瀏覽器沒有 randomUUID；session id 只需唯一，不需密碼學強度。
  return `sdk-${Date.now().toString(36)}-${
    Math.random().toString(36).slice(2, 10)
  }`;
}

function prependByte(first: number, rest: Uint8Array): Uint8Array {
  const joined = new Uint8Array(rest.length + 1);
  joined[0] = first;
  joined.set(rest, 1);
  return joined;
}

function littleEndianInt16(bytes: Uint8Array, length: number): Int16Array {
  const view = new DataView(bytes.buffer, bytes.byteOffset, length);
  const samples = new Int16Array(length / 2);
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = view.getInt16(index * 2, true);
  }
  return samples;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
