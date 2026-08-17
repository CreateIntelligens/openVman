import { inflate } from "pako";

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
    }) => Promise<AvatarRuntimeInstance>;
  }
}

export class AvatarRuntime {
  private chunkIndex = 0;
  private readonly instance: AvatarRuntimeInstance;
  private readonly idleLipSyncBypass: IdleLipSyncBypass | null;

  private constructor(
    instance: AvatarRuntimeInstance,
    idleLipSyncBypass: IdleLipSyncBypass | null,
  ) {
    this.instance = instance;
    this.idleLipSyncBypass = idleLipSyncBypass;
  }

  static async create(baseUrl: string): Promise<AvatarRuntime> {
    await loadRuntimeScript(`${baseUrl}/sdk/runtime/OpenVmanAvatarRuntime.js`);
    const idleLipSyncBypass = installIdleLipSyncBypass();
    if (!window.createQtAppInstance) {
      idleLipSyncBypass?.restore();
      throw new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        "Avatar runtime factory is unavailable.",
      );
    }
    try {
      const instance = await window.createQtAppInstance({
        locateFile: (path) => path.endsWith(".wasm")
          ? `${baseUrl}/sdk/runtime/OpenVmanAvatarRuntime.wasm`
          : path,
        onRuntimeInitialized() {},
      });
      return new AvatarRuntime(instance, idleLipSyncBypass);
    } catch (error) {
      idleLipSyncBypass?.restore();
      throw error;
    }
  }

  async loadCharacter(characterId: string, assetsBaseUrl: string): Promise<void> {
    const characterBaseUrl = `${assetsBaseUrl}/${encodeURIComponent(characterId)}`;
    const dataUrl = `${characterBaseUrl}/combined_data.json.gz`;
    const response = await fetch(dataUrl);
    if (!response.ok) {
      throw new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        `Character data request failed with HTTP ${response.status}.`,
      );
    }

    const payload = new Uint8Array(await response.arrayBuffer());
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
    video.src = `${characterBaseUrl}/01.webm`;
    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    const ready = waitForVideoReady(video, video.src);
    video.load();
    await ready;
    try {
      await video.play();
    } catch (error) {
      throw new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        `Avatar character video could not start: ${errorMessage(error)}.`,
      );
    }
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

  dispose(): void {
    this.idleLipSyncBypass?.resetSpeaking();
    this.idleLipSyncBypass?.restore();
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

function isGzip(payload: Uint8Array): boolean {
  return payload.length >= 2 && payload[0] === 0x1f && payload[1] === 0x8b;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function waitForVideoReady(
  video: HTMLVideoElement,
  src: string,
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
    }, 15_000);

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
