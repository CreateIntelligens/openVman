export type OpenVmanAvatarErrorCode =
  | "AUDIO_PLAYBACK_FAILED"
  | "AUTOPLAY_BLOCKED"
  | "CHAT_FAILED"
  | "DOM_CONFLICT"
  | "INSTANCE_EXISTS"
  | "INVALID_OPTIONS"
  | "RATE_LIMITED"
  | "RESOURCE_LOAD_FAILED"
  | "RUNTIME_DISPOSED"
  | "SPEECH_FAILED"
  | "UNAUTHORIZED";

export class OpenVmanAvatarError extends Error {
  readonly code: OpenVmanAvatarErrorCode;
  // 只有 RATE_LIMITED 會帶值，來自後端 Retry-After。
  readonly retryAfterSeconds?: number;

  constructor(
    code: OpenVmanAvatarErrorCode,
    message: string,
    retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "OpenVmanAvatarError";
    this.code = code;
    if (retryAfterSeconds !== undefined) {
      this.retryAfterSeconds = retryAfterSeconds;
    }
  }
}
