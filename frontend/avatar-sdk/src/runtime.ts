import { inflate } from "pako";

import { OpenVmanAvatarError } from "./errors";

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

  private constructor(instance: AvatarRuntimeInstance) {
    this.instance = instance;
  }

  static async create(baseUrl: string): Promise<AvatarRuntime> {
    await loadRuntimeScript(`${baseUrl}/sdk/runtime/OpenVmanAvatarRuntime.js`);
    if (!window.createQtAppInstance) {
      throw new OpenVmanAvatarError(
        "RESOURCE_LOAD_FAILED",
        "Avatar runtime factory is unavailable.",
      );
    }
    const instance = await window.createQtAppInstance({
      locateFile: (path) => path.endsWith(".wasm")
        ? `${baseUrl}/sdk/runtime/OpenVmanAvatarRuntime.wasm`
        : path,
      onRuntimeInitialized() {},
    });
    return new AvatarRuntime(instance);
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
    video.load();
    await video.play().catch(() => undefined);
  }

  clearAudio(): void {
    this.instance._clearAudio();
    this.chunkIndex = 0;
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
