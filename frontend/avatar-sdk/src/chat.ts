import { OpenVmanAvatarError } from "./errors";
import { readSseEvents } from "./sse";
import type { OpenVmanAvatarOptions } from "./types";

interface ChatResponseBody {
  reply?: unknown;
}

interface StreamErrorBody {
  detail?: unknown;
  status?: unknown;
}

type ConversationFailureCode = "CHAT_FAILED" | "SPEECH_FAILED";

export interface AvatarConversationDeps {
  interrupt(): void;
  onReply(text: string): void;
  onSentence(index: number, text: string): void;
  playAudio(source: ArrayBuffer): Promise<void>;
  queueAudio(source: ArrayBuffer): Promise<void>;
}

/** Thrown when the stream route is missing on this deployment. */
class StreamRouteMissing extends Error {}

export class AvatarConversation {
  private sessionId: string | null = null;
  private turn: AbortController | null = null;
  private streamRouteMissing = false;

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
    this.deps.onReply(reply);
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

    const speaker = new SentenceSpeaker(
      (segment) => this.requestSpeech(segment, signal),
      (audio) => this.deps.queueAudio(audio),
      () => signal.aborted,
    );
    const sentences: string[] = [];
    let reply: string | null = null;
    try {
      for await (const { event, data } of readSseEvents(response.body)) {
        if (signal.aborted) break;
        if (event === "sentence") {
          const sentence = sentenceText(data);
          if (!sentence) continue;
          this.deps.onSentence(sentences.length, sentence);
          sentences.push(sentence);
          speaker.add(sentence);
        } else if (event === "done") {
          reply = requireReply(data as ChatResponseBody);
          break;
        } else if (event === "error") {
          throw streamError(data as StreamErrorBody);
        }
      }
    } catch (error) {
      if (signal.aborted) return sentences.join("");
      // 出錯就停掉已經開口的部分與還沒送出的合成。
      this.interrupt();
      throw error instanceof OpenVmanAvatarError
        ? error
        : new OpenVmanAvatarError("CHAT_FAILED", errorMessage(error));
    }
    if (signal.aborted) return sentences.join("");
    if (reply === null) {
      this.interrupt();
      throw new OpenVmanAvatarError(
        "CHAT_FAILED",
        "Chat stream ended without a final reply.",
      );
    }

    // 整輪沒有任何句子事件時，整段回答一次合成，不能讓數位人不出聲。
    if (sentences.length === 0) speaker.add(reply);
    this.deps.onReply(reply);
    await speaker.finish();
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

  private async requestSpeech(
    text: string,
    signal: AbortSignal,
  ): Promise<ArrayBuffer | null> {
    const response = await this.send(
      `${this.resourceBaseUrl}/v1/audio/speech`,
      omitUndefined({
        input: text,
        provider: this.options.tts?.provider,
        voice: this.options.tts?.voice,
        // 同源 session 沒有 embed key 綁定專案，要靠這裡帶專案才套得到專案的聲音與分流。
        project_id: this.options.projectId,
        language: this.options.tts?.language,
      }),
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

  private ensureSessionId(): string {
    this.sessionId ??= createSessionId();
    return this.sessionId;
  }
}

/**
 * Speaks a streamed reply in order. One speech request runs at a time;
 * sentences that arrive meanwhile are joined into the next request, which
 * keeps the request count (and the embed key's quota) low and avoids the
 * pause each extra request would add before its audio.
 */
class SentenceSpeaker {
  private pending: string[] = [];
  private draining: Promise<void> | null = null;
  private playbacks: Promise<void>[] = [];
  private failure: unknown = null;

  constructor(
    private readonly synthesize: (text: string) => Promise<ArrayBuffer | null>,
    private readonly enqueue: (audio: ArrayBuffer) => Promise<void>,
    private readonly cancelled: () => boolean,
  ) {}

  add(text: string): void {
    if (this.failure || this.cancelled()) return;
    this.pending.push(text);
    this.draining ??= this.drain();
  }

  /** Resolves when everything added has been spoken; rejects on the first failure. */
  async finish(): Promise<void> {
    while (this.draining) await this.draining;
    await Promise.all(this.playbacks);
    if (this.failure) throw this.failure;
  }

  private async drain(): Promise<void> {
    while (this.pending.length && !this.failure && !this.cancelled()) {
      // 句子保留原本的空白與換行，接起來才跟完整回答一致。
      const segment = this.pending.join("");
      this.pending = [];
      if (!segment.trim()) continue;
      try {
        const audio = await this.synthesize(segment);
        if (!audio || this.cancelled()) break;
        this.playbacks.push(
          this.enqueue(audio).catch((error) => {
            this.failure ??= error;
          }),
        );
      } catch (error) {
        this.failure = error;
      }
    }
    this.pending = [];
    this.draining = null;
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
