import { inflate } from "pako";

import {
  installFrameSyncMarkerRepair,
  type FrameSyncMarkerRepair,
} from "../../shared/avatar/avatarFrameSyncRepair";
import type { AvatarAssets } from "./avatarAssets";
import { OpenVmanAvatarError } from "./errors";
import {
  installIdleLipSyncBypass,
  type IdleLipSyncBypass,
} from "./idleLipSyncBypass";

export interface AvatarRuntimeInstance {
  HEAPU8: Uint8Array;
  _clearAudio(): void;
  _free(pointer: number): void;
  _malloc(bytes: number): number;
  _processSecret(pointer: number): void;
  _setAudioBuffer(pointer: number, byteLength: number, index: number): void;
  stringToUTF8(value: string, pointer: number, maxBytes: number): void;
}

declare global {
  interface Window {
    characterVideo?: HTMLVideoElement;
    createQtAppInstance?: (options: {
      locateFile(path: string): string;
      onRuntimeInitialized(): void;
      wasmBinary?: ArrayBuffer;
    }) => Promise<AvatarRuntimeInstance>;
  }
}

export class AvatarRuntime {
  private chunkIndex = 0;
  private readonly instance: AvatarRuntimeInstance;
  private readonly idleLipSyncBypass: IdleLipSyncBypass | null;
  private readonly frameSyncMarkerRepair: FrameSyncMarkerRepair | null;
  private videoObjectUrl = "";
  private stopAwaitingGesture: (() => void) | null = null;

  private constructor(
    instance: AvatarRuntimeInstance,
    idleLipSyncBypass: IdleLipSyncBypass | null,
    frameSyncMarkerRepair: FrameSyncMarkerRepair | null,
  ) {
    this.instance = instance;
    this.idleLipSyncBypass = idleLipSyncBypass;
    this.frameSyncMarkerRepair = frameSyncMarkerRepair;
  }

  static async create(assets: AvatarAssets): Promise<AvatarRuntime> {
    await loadRuntimeScriptFrom(assets);
    const idleLipSyncBypass = installIdleLipSyncBypass();
    const frameSyncMarkerRepair = installFrameSyncMarkerRepair();
    if (!window.createQtAppInstance) {
      idleLipSyncBypass?.restore();
      frameSyncMarkerRepair?.restore();
      throw new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        "Avatar runtime factory is unavailable.",
      );
    }
    try {
      const instance = await window.createQtAppInstance({
        // 已經拿到的 wasm 直接交給 runtime，不必再下載；locateFile 只是保底。
        locateFile: (path) => path.endsWith(".wasm") ? assets.runtimeWasmUrl : path,
        onRuntimeInitialized() {},
        wasmBinary: assets.runtimeWasm,
      });
      return new AvatarRuntime(instance, idleLipSyncBypass, frameSyncMarkerRepair);
    } catch (error) {
      idleLipSyncBypass?.restore();
      frameSyncMarkerRepair?.restore();
      throw error;
    }
  }

  async loadCharacter(assets: AvatarAssets): Promise<void> {
    const payload = assets.characterData;
    const text = isGzip(payload)
      ? inflate(payload, { to: "string" })
      : new TextDecoder().decode(payload);
    const encoded = new TextEncoder().encode(text);
    const pointer = this.instance._malloc(encoded.length + 1);
    try {
      this.instance.stringToUTF8(text, pointer, encoded.length + 1);
      this.instance._processSecret(pointer);
    } finally {
      this.instance._free(pointer);
    }

    const video = window.characterVideo;
    if (!video) {
      throw new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        "Avatar character video was not created by the runtime.",
      );
    }
    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    await this.loadVideoSource(video, assets);
    try {
      await video.play();
    } catch (error) {
      if (!isAutoplayBlocked(error)) {
        throw new OpenVmanAvatarError(
          "RESOURCE_LOAD_FAILED",
          `Avatar character video could not start: ${errorMessage(error)}.`,
        );
      }
      // 影片已經載好，只是瀏覽器不准自己播（iOS 省電模式、還沒互動過）：不讓 init() 失敗，
      // 停在第一格，等使用者第一次點擊或按鍵再播。
      this.awaitGesture(video);
    }
  }

  /** True while the character video is loaded but waits for a tap or key press to play. */
  get videoAwaitingGesture(): boolean {
    return this.stopAwaitingGesture !== null;
  }

  private async loadVideoSource(video: HTMLVideoElement, assets: AvatarAssets): Promise<void> {
    if (await this.tryBlobVideo(video, assets.video)) return;
    // 存在瀏覽器的那份播不了：清掉重新下載，下次開頁也會換成新存的。
    const fresh = assets.reloadVideo ? await assets.reloadVideo().catch(() => null) : null;
    if (fresh && await this.tryBlobVideo(video, fresh)) return;
    // 頁面的 CSP（media-src）不允許 blob: 時改從原網址播（這時離線就播不到）。
    await loadVideo(video, assets.videoUrl, VIDEO_URL_TIMEOUT_MS);
  }

  private async tryBlobVideo(video: HTMLVideoElement, blob: Blob): Promise<boolean> {
    this.releaseVideoUrl();
    this.videoObjectUrl = URL.createObjectURL(blob);
    try {
      await loadVideo(video, this.videoObjectUrl, VIDEO_BLOB_TIMEOUT_MS);
      return true;
    } catch {
      this.releaseVideoUrl();
      return false;
    }
  }

  private releaseVideoUrl(): void {
    if (this.videoObjectUrl) URL.revokeObjectURL(this.videoObjectUrl);
    this.videoObjectUrl = "";
  }

  private awaitGesture(video: HTMLVideoElement): void {
    // iOS 只認手勢處理函式裡「同步」呼叫的 play()，所以在事件裡直接呼叫。
    const retry = (): void => {
      void video.play().then(() => this.stopAwaitingGesture?.()).catch(() => {});
    };
    for (const type of GESTURE_EVENTS) {
      window.addEventListener(type, retry, { capture: true, passive: true });
    }
    this.stopAwaitingGesture = () => {
      for (const type of GESTURE_EVENTS) window.removeEventListener(type, retry, { capture: true });
      this.stopAwaitingGesture = null;
    };
  }

  clearAudio(): void {
    this.instance._clearAudio();
    this.chunkIndex = 0;
  }

  beginSpeaking(): void {
    this.idleLipSyncBypass?.beginSpeaking();
  }

  endSpeaking(): void {
    this.idleLipSyncBypass?.endSpeaking();
  }

  resetSpeaking(): void {
    this.idleLipSyncBypass?.resetSpeaking();
  }

  /**
   * Stops pasting the mouth when the WebGL mouth canvas loses its context.
   * The closed runtime cannot rebuild its GL objects and only one runtime may
   * exist per page, so lip sync stays off until the page reloads.
   */
  watchGlContext(onLost: () => void): () => void {
    const canvas = document.getElementById("canvas_gl");
    if (!canvas) return () => {};
    const handleLost = (event: Event): void => {
      event.preventDefault();
      this.idleLipSyncBypass?.suppressPatches();
      onLost();
    };
    canvas.addEventListener("webglcontextlost", handleLost);
    return () => canvas.removeEventListener("webglcontextlost", handleLost);
  }

  dispose(): void {
    this.stopAwaitingGesture?.();
    this.releaseVideoUrl();
    this.idleLipSyncBypass?.resetSpeaking();
    this.idleLipSyncBypass?.restore();
    this.frameSyncMarkerRepair?.restore();
  }

  pushAudio(pcm: Int16Array): void {
    const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
    const pointer = this.instance._malloc(bytes.length);
    try {
      this.instance.HEAPU8.set(bytes, pointer);
      this.instance._setAudioBuffer(pointer, bytes.length, this.chunkIndex++);
    } finally {
      this.instance._free(pointer);
    }
  }
}

// 本機的 blob 很快就能解碼；卡住多半是 Safari 不肯播這份 blob，不必等滿網路的逾時。
const VIDEO_BLOB_TIMEOUT_MS = 8_000;
const VIDEO_URL_TIMEOUT_MS = 15_000;
const GESTURE_EVENTS = ["pointerdown", "touchend", "keydown"] as const;

function isAutoplayBlocked(error: unknown): boolean {
  return (error as { name?: unknown } | null)?.name === "NotAllowedError";
}

function loadVideo(video: HTMLVideoElement, src: string, timeoutMs: number): Promise<void> {
  video.src = src;
  const ready = waitForVideoReady(video, src, timeoutMs);
  video.load();
  return ready;
}

function isGzip(payload: Uint8Array): boolean {
  return payload.length >= 2 && payload[0] === 0x1f && payload[1] === 0x8b;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function waitForVideoReady(
  video: HTMLVideoElement,
  src: string,
  timeoutMs: number,
): Promise<void> {
  if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        `Avatar character video timed out while loading ${src}.`,
      ));
    }, timeoutMs);

    const cleanup = (): void => {
      window.clearTimeout(timeout);
      video.removeEventListener("canplay", handleCanPlay);
      video.removeEventListener("error", handleError);
      video.removeEventListener("loadeddata", handleCanPlay);
    };
    const handleCanPlay = (): void => {
      cleanup();
      resolve();
    };
    const handleError = (): void => {
      cleanup();
      const mediaMessage = video.error?.message
        ? `: ${video.error.message}`
        : "";
      reject(new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        `Avatar character video failed to load ${src}${mediaMessage}.`,
      ));
    };

    video.addEventListener("canplay", handleCanPlay, { once: true });
    video.addEventListener("error", handleError, { once: true });
    video.addEventListener("loadeddata", handleCanPlay, { once: true });

    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      handleCanPlay();
    }
  });
}

async function loadRuntimeScriptFrom(assets: AvatarAssets): Promise<void> {
  if (window.createQtAppInstance) return;
  const objectUrl = URL.createObjectURL(assets.runtimeScript);
  try {
    await loadRuntimeScript(objectUrl);
  } catch {
    // 頁面的 CSP 不允許 blob: 腳本時改從網址載（這時離線就載不到）。
    await loadRuntimeScript(assets.runtimeScriptUrl);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

async function loadRuntimeScript(src: string): Promise<void> {
  if (window.createQtAppInstance) return;

  await new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.async = true;
    script.dataset.openvmanRuntime = "true";
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new OpenVmanAvatarError(
      "RESOURCE_LOAD_FAILED",
      `Unable to load ${src}.`,
    ));
    document.body.append(script);
  });
}
