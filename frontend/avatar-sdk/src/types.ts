export type OpenVmanAvatarEventType =
  | "destroyed"
  | "error"
  | "ready"
  | "reply"
  | "sentence"
  | "speaking";

// 對話鎖定的語言；不含台語（nan），台語沒有穩定的書寫形式可鎖。
export type OpenVmanAvatarLanguage = "en" | "es" | "ja" | "ko" | "zh";

export type OpenVmanAvatarAudioOutput = "speaker" | "silent";

export interface OpenVmanAvatarTtsOptions {
  provider?: string;
  voice?: string;
  // 回答要唸的語言（zh、en、nan…）。nan 且專案開了台語分流時改用台語引擎。
  language?: string;
}

export interface OpenVmanAvatarOptions {
  assetsBaseUrl?: string;
  // pushPcm 每段話開頭先扣住的毫秒數（預設 150），讓嘴型模型拿到足夠的音訊；
  // 0 表示收到就播。
  audioLeadMs?: number;
  // 宿主自行播放音訊時，可用 silent 只驅動嘴型。
  audioOutput?: OpenVmanAvatarAudioOutput;
  // 預設 true：人物與播放程式存在瀏覽器裡，之後開頁面不再下載，伺服器暫時連不上也顯示得出來。
  cacheAssets?: boolean;
  characterId?: string;
  container?: HTMLElement;
  // 設定後 ask() 以 embed key 驗證，未設定則沿用同源 session cookie。
  embedKey?: string;
  height?: string;
  // 指定後每次 ask() 都帶 language：整場對話一律用這個語言回答，知識也只查這個語言。
  // greet() 也用它挑開場白。
  language?: OpenVmanAvatarLanguage;
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
  // sessionId／traceId 讓宿主頁面把這一輪對到 openVman 後端的對話紀錄與 log；後端沒給時為空字串。
  reply: { text: string; type: "reply"; sessionId: string; traceId: string };
  // 串流回答每到一句派送一次，index 從 0 起算；整段回答以 reply 為準。
  sentence: { index: number; text: string; type: "sentence" };
  speaking: { state: "start" | "stop"; type: "speaking" };
}

export type OpenVmanAvatarEventHandler<T extends OpenVmanAvatarEventType> = (
  event: OpenVmanAvatarEventMap[T],
) => void;

export interface OpenVmanAvatarInstance {
  ask(text: string): Promise<string>;
  /** True when this init downloaded nothing (every file came from the browser's cache). */
  readonly assetsFromCache: boolean;
  destroy(): void;
  /**
   * 念出這個人設在 `language` 下設定的開場白（字幕、語音、嘴形），不進對話、不呼叫模型。
   * 沒設 `language` 會丟錯；這個語言沒有開場白時什麼都不做。
   */
  greet(): Promise<void>;
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
