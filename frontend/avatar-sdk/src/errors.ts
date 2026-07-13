export type OpenVmanAvatarErrorCode =
  | "AUDIO_PLAYBACK_FAILED"
  | "AUTOPLAY_BLOCKED"
  | "DOM_CONFLICT"
  | "INSTANCE_EXISTS"
  | "INVALID_OPTIONS"
  | "RESOURCE_LOAD_FAILED"
  | "RUNTIME_DISPOSED";

export class OpenVmanAvatarError extends Error {
  readonly code: OpenVmanAvatarErrorCode;

  constructor(code: OpenVmanAvatarErrorCode, message: string) {
    super(message);
    this.name = "OpenVmanAvatarError";
    this.code = code;
  }
}
