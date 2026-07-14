import { AvatarAudio } from "./audio";
import { createAvatarDom, removeAvatarDom } from "./dom";
import { OpenVmanAvatarError } from "./errors";
import { AvatarRuntime } from "./runtime";
import type {
  OpenVmanAvatarCharacter,
  OpenVmanAvatarEventHandler,
  OpenVmanAvatarEventMap,
  OpenVmanAvatarEventType,
  OpenVmanAvatarGlobal,
  OpenVmanAvatarInstance,
  OpenVmanAvatarOptions,
} from "./types";

declare global {
  interface Window {
    OpenVmanAvatar: OpenVmanAvatarGlobal;
  }
}

const scriptUrl = new URL(
  (document.currentScript as HTMLScriptElement | null)?.src ?? window.location.href,
);
const resourceBaseUrl = scriptUrl.origin;
let activeInstance: OpenVmanAvatarInstance | null = null;
let activeInitPromise: Promise<OpenVmanAvatarInstance> | null = null;
let activeSignature = "";
let runtimeDisposed = false;
let nextContainerId = 1;
const containerIds = new WeakMap<HTMLElement, number>();

function containerId(container?: HTMLElement): string {
  if (!container) return "default";
  let id = containerIds.get(container);
  if (!id) {
    id = nextContainerId++;
    containerIds.set(container, id);
  }
  return String(id);
}

function signature(options: OpenVmanAvatarOptions): string {
  return JSON.stringify({
    assetsBaseUrl: options.assetsBaseUrl,
    characterId: options.characterId,
    container: containerId(options.container),
    height: options.height,
    position: options.position,
    width: options.width,
    zIndex: options.zIndex,
  });
}

async function init(
  options: OpenVmanAvatarOptions,
): Promise<OpenVmanAvatarInstance> {
  options ??= {};
  if (runtimeDisposed) {
    throw new OpenVmanAvatarError(
      "RUNTIME_DISPOSED",
      "Reload the page before initializing the avatar runtime again.",
    );
  }

  const nextSignature = signature(options);
  if (activeInstance) {
    if (activeSignature === nextSignature) return activeInstance;
    throw new OpenVmanAvatarError(
      "INSTANCE_EXISTS",
      "Only one avatar runtime can exist during a page lifetime.",
    );
  }

  if (activeInitPromise) {
    if (activeSignature === nextSignature) return activeInitPromise;
    throw new OpenVmanAvatarError(
      "INSTANCE_EXISTS",
      "Another avatar runtime is already initializing.",
    );
  }

  activeSignature = nextSignature;
  activeInitPromise = createInstance(options).catch((error) => {
    activeInitPromise = null;
    activeSignature = "";
    throw error;
  });
  return activeInitPromise;
}

async function listCharacters(): Promise<OpenVmanAvatarCharacter[]> {
  let response: Response;
  try {
    response = await fetch(`${resourceBaseUrl}/characters`);
  } catch (error) {
    throw new OpenVmanAvatarError(
      "RESOURCE_LOAD_FAILED",
      error instanceof Error ? error.message : String(error),
    );
  }
  if (!response.ok) {
    throw new OpenVmanAvatarError(
      "RESOURCE_LOAD_FAILED",
      `Character list request failed with HTTP ${response.status}.`,
    );
  }
  const body = (await response.json()) as {
    characters?: { char_id: string; label: string }[];
  };
  return (body.characters ?? []).map((character) => ({
    charId: character.char_id,
    label: character.label,
  }));
}

async function createInstance(
  options: OpenVmanAvatarOptions,
): Promise<OpenVmanAvatarInstance> {
  const dom = createAvatarDom(options);
  const handlers = new Map<
    OpenVmanAvatarEventType,
    Set<OpenVmanAvatarEventHandler<OpenVmanAvatarEventType>>
  >();
  let destroyed = false;

  let runtime: AvatarRuntime | null = null;
  try {
    runtime = await AvatarRuntime.create(resourceBaseUrl);
    const assetsBaseUrl = new URL(
      options.assetsBaseUrl ?? "/assets/",
      `${resourceBaseUrl}/`,
    ).toString().replace(/\/$/, "");
    await runtime.loadCharacter(options.characterId ?? "000", assetsBaseUrl);
  } catch (error) {
    if (runtime) runtimeDisposed = true;
    removeAvatarDom(dom);
    throw error instanceof OpenVmanAvatarError
      ? error
      : new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        error instanceof Error ? error.message : String(error),
      );
  }
  const emit = <T extends OpenVmanAvatarEventType>(
    type: T,
    event: OpenVmanAvatarEventMap[T],
  ): void => {
    for (const handler of handlers.get(type) ?? []) handler(event);
  };
  const audio = new AvatarAudio(runtime, (speaking) => {
    emit("speaking", {
      state: speaking ? "start" : "stop",
      type: "speaking",
    });
  });

  const runAudio = async (operation: () => Promise<void>): Promise<void> => {
    try {
      await operation();
    } catch (error) {
      const publicError = error instanceof OpenVmanAvatarError
        ? error
        : new OpenVmanAvatarError(
          "AUDIO_PLAYBACK_FAILED",
          error instanceof Error ? error.message : String(error),
        );
      emit("error", {
        code: publicError.code,
        message: publicError.message,
        type: "error",
      });
      throw publicError;
    }
  };

  const instance: OpenVmanAvatarInstance = {
    destroy() {
      if (destroyed) return;
      destroyed = true;
      runtimeDisposed = true;
      audio.destroy();
      removeAvatarDom(dom);
      emit("destroyed", { type: "destroyed" });
      handlers.clear();
      activeInstance = null;
    },
    interrupt() {
      audio.interrupt();
    },
    off(type, handler) {
      handlers.get(type)?.delete(
        handler as OpenVmanAvatarEventHandler<OpenVmanAvatarEventType>,
      );
    },
    on(type, handler) {
      const existing = handlers.get(type) ?? new Set();
      existing.add(
        handler as OpenVmanAvatarEventHandler<OpenVmanAvatarEventType>,
      );
      handlers.set(type, existing);
      if (type === "ready" && !destroyed) {
        queueMicrotask(() => handler({ type: "ready" } as never));
      }
    },
    async playAudio(source) {
      await runAudio(() => audio.playAudio(source));
    },
    async pushPcm(chunk) {
      await runAudio(() => audio.pushPcm(chunk));
    },
  };

  activeInstance = instance;
  activeInitPromise = null;
  return instance;
}

window.OpenVmanAvatar = Object.freeze({ init, listCharacters, resourceBaseUrl });
