export type OpenVmanAvatarEventType =
  | "destroyed"
  | "error"
  | "ready"
  | "reply"
  | "speaking";

export type OpenVmanAvatarAudioOutput = "speaker" | "silent";

export interface OpenVmanAvatarTtsOptions {
  provider?: string;
  voice?: string;
}

export interface OpenVmanAvatarOptions {
  assetsBaseUrl?: string;
  // 宿主自行播放音訊時，可用 silent 只驅動嘴型。
  audioOutput?: OpenVmanAvatarAudioOutput;
  characterId?: string;
  container?: HTMLElement;
  // 設定後 ask() 以 embed key 驗證，未設定則沿用同源 session cookie。
  embedKey?: string;
  height?: string;
  personaId?: string;
  position?: "bottom-left" | "bottom-right";
  projectId?: string;
  tts?: OpenVmanAvatarTtsOptions;
  width?: string;
  zIndex?: number;
}

export interface OpenVmanAvatarEventMap {
  destroyed: { type: "destroyed" };
  error: {
    code: string;
    message: string;
    retryAfterSeconds?: number;
    type: "error";
  };
  ready: { type: "ready" };
  reply: { text: string; type: "reply" };
  speaking: { state: "start" | "stop"; type: "speaking" };
}

export type OpenVmanAvatarEventHandler<T extends OpenVmanAvatarEventType> = (
  event: OpenVmanAvatarEventMap[T],
) => void;

export interface OpenVmanAvatarInstance {
  ask(text: string): Promise<string>;
  destroy(): void;
  interrupt(): void;
  off<T extends OpenVmanAvatarEventType>(
    type: T,
    handler: OpenVmanAvatarEventHandler<T>,
  ): void;
  on<T extends OpenVmanAvatarEventType>(
    type: T,
    handler: OpenVmanAvatarEventHandler<T>,
  ): void;
  playAudio(source: Blob | ArrayBuffer): Promise<void>;
  pushPcm(chunk: Int16Array): Promise<void>;
}

export interface OpenVmanAvatarCharacter {
  charId: string;
  label: string;
}

export interface OpenVmanAvatarGlobal {
  init(options: OpenVmanAvatarOptions): Promise<OpenVmanAvatarInstance>;
  listCharacters(): Promise<OpenVmanAvatarCharacter[]>;
  readonly resourceBaseUrl: string;
}
