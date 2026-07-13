export type OpenVmanAvatarEventType =
  | "destroyed"
  | "error"
  | "ready"
  | "speaking";

export interface OpenVmanAvatarOptions {
  apiKey: string;
  assetsBaseUrl?: string;
  characterId?: string;
  container?: HTMLElement;
  height?: string;
  persona?: string;
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
  setPersona(persona: string): void;
  speak(text: string): Promise<void>;
}

export interface OpenVmanAvatarGlobal {
  init(options: OpenVmanAvatarOptions): Promise<OpenVmanAvatarInstance>;
  readonly resourceBaseUrl: string;
}
