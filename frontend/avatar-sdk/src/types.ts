export type OpenVmanAvatarEventType =
  | "destroyed"
  | "error"
  | "ready"
  | "speaking";

export interface OpenVmanAvatarOptions {
  assetsBaseUrl?: string;
  characterId?: string;
  container?: HTMLElement;
  height?: string;
  position?: "bottom-left" | "bottom-right";
  width?: string;
  zIndex?: number;
}

export interface OpenVmanAvatarEventMap {
  destroyed: { type: "destroyed" };
  error: { code: string; message: string; type: "error" };
  ready: { type: "ready" };
  speaking: { state: "start" | "stop"; type: "speaking" };
}

export type OpenVmanAvatarEventHandler<T extends OpenVmanAvatarEventType> = (
  event: OpenVmanAvatarEventMap[T],
) => void;

export interface OpenVmanAvatarInstance {
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

export interface OpenVmanAvatarGlobal {
  init(options: OpenVmanAvatarOptions): Promise<OpenVmanAvatarInstance>;
  readonly resourceBaseUrl: string;
}
