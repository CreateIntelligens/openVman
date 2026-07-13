import { AvatarAudio } from "./audio";
import { createAvatarDom, removeAvatarDom } from "./dom";
import { OpenVmanAvatarError } from "./errors";
import { AvatarRuntime } from "./runtime";
import type {
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
    apiKey: options.apiKey,
    assetsBaseUrl: options.assetsBaseUrl,
    characterId: options.characterId,
    container: containerId(options.container),
    height: options.height,
    persona: options.persona,
    position: options.position,
    width: options.width,
    zIndex: options.zIndex,
  });
}

async function init(
  options: OpenVmanAvatarOptions,
): Promise<OpenVmanAvatarInstance> {
  if (!options?.apiKey?.trim()) {
    throw new OpenVmanAvatarError("INVALID_OPTIONS", "apiKey is required.");
  }
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

async function createInstance(
  options: OpenVmanAvatarOptions,
): Promise<OpenVmanAvatarInstance> {
  const dom = createAvatarDom(options);
  const handlers = new Map<
    OpenVmanAvatarEventType,
    Set<OpenVmanAvatarEventHandler<OpenVmanAvatarEventType>>
  >();
  let persona = options.persona ?? "";
  let destroyed = false;
  let speaking = false;
  let speechController: AbortController | null = null;

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
  const audio = new AvatarAudio(runtime);

  const emit = <T extends OpenVmanAvatarEventType>(
    type: T,
    event: OpenVmanAvatarEventMap[T],
  ): void => {
    for (const handler of handlers.get(type) ?? []) handler(event);
  };

  const instance: OpenVmanAvatarInstance = {
    destroy() {
      if (destroyed) return;
      destroyed = true;
      runtimeDisposed = true;
      speechController?.abort();
      speechController = null;
      audio.destroy();
      removeAvatarDom(dom);
      emit("destroyed", { type: "destroyed" });
      handlers.clear();
      activeInstance = null;
    },
    interrupt() {
      speechController?.abort();
      speechController = null;
      audio.interrupt();
      if (speaking) {
        speaking = false;
        emit("speaking", { state: "stop", type: "speaking" });
      }
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
    setPersona(nextPersona) {
      persona = nextPersona;
      void persona;
    },
    async speak(text) {
      const normalizedText = text.trim();
      if (!normalizedText) {
        throw new OpenVmanAvatarError("INVALID_OPTIONS", "Speech text is required.");
      }
      instance.interrupt();
      const controller = new AbortController();
      speechController = controller;
      const audioReady = audio.prepare();
      try {
        const responsePromise = fetch(`${resourceBaseUrl}/api/embed/tts`, {
          body: JSON.stringify({ text }),
          headers: {
            Accept: "audio/*",
            Authorization: `Bearer ${options.apiKey}`,
            "Content-Type": "application/json",
          },
          method: "POST",
          signal: controller.signal,
        });
        void responsePromise.catch(() => undefined);
        await audioReady;
        const response = await responsePromise;
        if (!response.ok) {
          throw new OpenVmanAvatarError(
            response.status === 401 || response.status === 403
              ? "API_ERROR"
              : "TTS_FAILED",
            `TTS request failed with HTTP ${response.status}.`,
          );
        }
        speaking = true;
        emit("speaking", { state: "start", type: "speaking" });
        await audio.speak(response);
      } catch (error) {
        const interrupted = controller.signal.aborted;
        if (!interrupted) controller.abort();
        if (interrupted) return;
        const publicError = error instanceof OpenVmanAvatarError
          ? error
          : new OpenVmanAvatarError(
            "TTS_FAILED",
            error instanceof Error ? error.message : String(error),
          );
        emit("error", {
          code: publicError.code,
          message: publicError.message,
          type: "error",
        });
        throw publicError;
      } finally {
        if (speechController === controller) speechController = null;
        if (speaking) {
          speaking = false;
          emit("speaking", { state: "stop", type: "speaking" });
        }
      }
    },
  };

  activeInstance = instance;
  activeInitPromise = null;
  return instance;
}

window.OpenVmanAvatar = Object.freeze({ init, resourceBaseUrl });
