import { AvatarAudio, DEFAULT_AUDIO_LEAD_MS } from "./audio";
import { clearAssetCache } from "./assetCache";
import { loadAvatarAssets } from "./avatarAssets";
import { AvatarConversation } from "./chat";
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

function audioLeadMs(value: number | undefined): number {
  if (value === undefined) return DEFAULT_AUDIO_LEAD_MS;
  if (!Number.isFinite(value) || value < 0 || value > 2000) {
    throw new OpenVmanAvatarError(
      "INVALID_OPTIONS",
      "audioLeadMs must be a number of milliseconds between 0 and 2000.",
    );
  }
  return value;
}

function signature(options: OpenVmanAvatarOptions): string {
  return JSON.stringify({
    assetsBaseUrl: options.assetsBaseUrl,
    audioLeadMs: options.audioLeadMs,
    audioOutput: options.audioOutput ?? "speaker",
    cacheAssets: options.cacheAssets ?? true,
    characterId: options.characterId,
    container: containerId(options.container),
    embedKey: options.embedKey,
    height: options.height,
    language: options.language,
    personaId: options.personaId,
    position: options.position,
    projectId: options.projectId,
    ttsProvider: options.tts?.provider,
    ttsVoice: options.tts?.voice,
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
    response = await fetch(`${resourceBaseUrl}/api/v1/characters`);
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
  const assetsBaseUrl = new URL(
    options.assetsBaseUrl ?? "/static/characters/",
    `${resourceBaseUrl}/`,
  ).toString().replace(/\/$/, "");
  // 先把檔案都拿到（快取或網路）才建立 runtime：網路失敗時頁面上什麼都還沒建，可以直接再 init()。
  const assets = await loadAvatarAssets(
    resourceBaseUrl,
    assetsBaseUrl,
    options.characterId ?? "000",
    options.cacheAssets ?? true,
  ).catch((error: unknown) => {
    throw error instanceof OpenVmanAvatarError
      ? error
      : new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        error instanceof Error ? error.message : String(error),
      );
  });
  const dom = createAvatarDom(options);
  const handlers = new Map<
    OpenVmanAvatarEventType,
    Set<OpenVmanAvatarEventHandler<OpenVmanAvatarEventType>>
  >();
  let destroyed = false;

  let runtime: AvatarRuntime | null = null;
  try {
    runtime = await AvatarRuntime.create(assets);
    await runtime.loadCharacter(assets);
  } catch (error) {
    if (runtime) {
      runtime.dispose();
      runtimeDisposed = true;
    }
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
  const stopWatchingGl = runtime.watchGlContext(() => {
    emit("error", {
      code: "WEBGL_CONTEXT_LOST",
      message: "The browser dropped the lip-sync canvas; lip sync is off until the page reloads.",
      type: "error",
    });
  });
  const audio = new AvatarAudio(
    runtime,
    (speaking) => {
      emit("speaking", {
        state: speaking ? "start" : "stop",
        type: "speaking",
      });
    },
    options.audioOutput ?? "speaker",
    audioLeadMs(options.audioLeadMs),
  );

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

  const conversation = new AvatarConversation(resourceBaseUrl, options, {
    interrupt: () => audio.interrupt(),
    onReply: (text, details) => emit("reply", { text, type: "reply", ...details }),
    onSentence: (index, text) =>
      emit("sentence", { index, text, type: "sentence" }),
    playAudio: (source) => audio.playAudio(source),
    pushPcm: (chunk) => audio.pushPcm(chunk),
    untilIdle: () => audio.untilIdle(),
  });

  const videoBlockedEvent = {
    code: "AUTOPLAY_BLOCKED",
    message: "The character video starts after a tap or key press on the page.",
    type: "error",
  } as const;
  const instance: OpenVmanAvatarInstance = {
    assetsFromCache: assets.fromCache,
    get videoAwaitingGesture() {
      return runtime.videoAwaitingGesture;
    },
    async ask(text) {
      try {
        return await conversation.ask(text);
      } catch (error) {
        const publicError = error instanceof OpenVmanAvatarError
          ? error
          : new OpenVmanAvatarError(
            "CHAT_FAILED",
            error instanceof Error ? error.message : String(error),
          );
        emit("error", {
          code: publicError.code,
          message: publicError.message,
          ...(publicError.retryAfterSeconds === undefined
            ? {}
            : { retryAfterSeconds: publicError.retryAfterSeconds }),
          type: "error",
        });
        throw publicError;
      }
    },
    async greet() {
      try {
        await conversation.greet();
      } catch (error) {
        const publicError = error instanceof OpenVmanAvatarError
          ? error
          : new OpenVmanAvatarError(
            "CHAT_FAILED",
            error instanceof Error ? error.message : String(error),
          );
        emit("error", {
          code: publicError.code,
          message: publicError.message,
          ...(publicError.retryAfterSeconds === undefined
            ? {}
            : { retryAfterSeconds: publicError.retryAfterSeconds }),
          type: "error",
        });
        throw publicError;
      }
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      runtimeDisposed = true;
      conversation.interrupt();
      audio.destroy();
      stopWatchingGl();
      runtime.dispose();
      removeAvatarDom(dom);
      emit("destroyed", { type: "destroyed" });
      handlers.clear();
      activeInstance = null;
    },
    interrupt() {
      // 連同進行中的對話串流與合成一起停，否則回答會繼續到、繼續念。
      conversation.interrupt();
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
      // init() 時影片被擋下來的話，訂閱 error 的頁面才知道要請使用者點一下。
      if (type === "error" && !destroyed && runtime.videoAwaitingGesture) {
        queueMicrotask(() => {
          if (runtime.videoAwaitingGesture) handler(videoBlockedEvent as never);
        });
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

window.OpenVmanAvatar = Object.freeze({ init, listCharacters, clearAssetCache, resourceBaseUrl });
