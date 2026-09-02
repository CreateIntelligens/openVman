import { OpenVmanAvatarError } from "./errors";
import type { OpenVmanAvatarOptions } from "./types";

interface ChatResponseBody {
  reply?: unknown;
}

export interface AvatarConversationDeps {
  interrupt(): void;
  onReply(text: string): void;
  playAudio(source: ArrayBuffer): Promise<void>;
}

export class AvatarConversation {
  private sessionId: string | null = null;

  constructor(
    private readonly resourceBaseUrl: string,
    private readonly options: OpenVmanAvatarOptions,
    private readonly deps: AvatarConversationDeps,
  ) {}

  async ask(text: string): Promise<string> {
    // 新的一輪必須先掐掉上一輪還在播的語音，避免兩段答案疊在一起。
    this.deps.interrupt();

    const reply = await this.requestChat(text);
    this.deps.onReply(reply);
    const audio = await this.requestSpeech(reply);
    await this.deps.playAudio(audio);
    return reply;
  }

  private async requestChat(text: string): Promise<string> {
    const response = await this.send(
      `${this.resourceBaseUrl}/api/v1/chat`,
      omitUndefined({
        message: text,
        persona_id: this.options.personaId,
        project_id: this.options.projectId,
        session_id: this.ensureSessionId(),
      }),
      "CHAT_FAILED",
    );

    let body: ChatResponseBody;
    try {
      body = (await response.json()) as ChatResponseBody;
    } catch (error) {
      throw new OpenVmanAvatarError("CHAT_FAILED", errorMessage(error));
    }
    if (typeof body.reply !== "string" || body.reply.length === 0) {
      throw new OpenVmanAvatarError(
        "CHAT_FAILED",
        "Chat response did not contain a reply.",
      );
    }
    return body.reply;
  }

  private async requestSpeech(text: string): Promise<ArrayBuffer> {
    const response = await this.send(
      `${this.resourceBaseUrl}/v1/audio/speech`,
      omitUndefined({
        input: text,
        provider: this.options.tts?.provider,
        voice: this.options.tts?.voice,
      }),
      "SPEECH_FAILED",
    );
    try {
      return await response.arrayBuffer();
    } catch (error) {
      throw new OpenVmanAvatarError("SPEECH_FAILED", errorMessage(error));
    }
  }

  private async send(
    url: string,
    payload: Record<string, unknown>,
    failureCode: "CHAT_FAILED" | "SPEECH_FAILED",
  ): Promise<Response> {
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
      });
    } catch (error) {
      throw new OpenVmanAvatarError(failureCode, errorMessage(error));
    }

    if (!response.ok) throw httpError(response, failureCode);
    return response;
  }

  private ensureSessionId(): string {
    this.sessionId ??= createSessionId();
    return this.sessionId;
  }
}

function httpError(
  response: Response,
  failureCode: "CHAT_FAILED" | "SPEECH_FAILED",
): OpenVmanAvatarError {
  if (response.status === 401 || response.status === 403) {
    return new OpenVmanAvatarError(
      "UNAUTHORIZED",
      `Request rejected with HTTP ${response.status}.`,
    );
  }
  if (response.status === 429) {
    return new OpenVmanAvatarError(
      "RATE_LIMITED",
      "Request rejected with HTTP 429.",
      retryAfterSeconds(response),
    );
  }
  return new OpenVmanAvatarError(
    failureCode,
    `Request failed with HTTP ${response.status}.`,
  );
}

function retryAfterSeconds(response: Response): number | undefined {
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
