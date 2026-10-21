export type OpenVmanAvatarEventType =
  | "destroyed"
  | "error"
  | "ready"
  | "reply"
  | "sentence"
  | "speaking";

export type OpenVmanAvatarAudioOutput = "speaker" | "silent";

export interface OpenVmanAvatarTtsOptions {
  provider?: string;
  voice?: string;
  // 回答要唸的語言（zh、en、nan…）。nan 且專案開了台語分流時改用台語引擎。
  language?: string;
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
  // 串流回答每到一句派送一次，index 從 0 起算；整段回答以 reply 為準。
  sentence: { index: number; text: string; type: "sentence" };
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
