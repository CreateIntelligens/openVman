import {
  downloadAsset,
  forgetAssetGroup,
  isTransientAssetError,
  loadAssetGroup,
  type LoadedAsset,
} from "./assetCache";

// 伺服器短暫連不上（重啟、換版）時先等一下再試；明確拒絕（401／403／404）不重試。
const RETRY_DELAYS_MS = [1_000, 3_000];

export interface AvatarAssets {
  characterData: Uint8Array;
  /** True when every file came from the browser's copy, i.e. nothing was downloaded. */
  fromCache: boolean;
  runtimeScript: Blob;
  runtimeScriptUrl: string;
  runtimeWasm: ArrayBuffer;
  runtimeWasmUrl: string;
  video: Blob;
  videoUrl: string;
  /**
   * Forgets the stored character files and downloads the video again; set only
   * when the video came from the browser's copy (a fresh download needs no retry).
   */
  reloadVideo?: () => Promise<Blob>;
}

/**
 * Safari on iOS will not play a video from a blob URL whose blob is backed by a
 * Cache Storage file (first visit works, every later visit fails). A copy held in
 * memory plays like a fresh download.
 */
async function inMemory(blob: Blob, fallbackType: string): Promise<Blob> {
  return new Blob([await blob.arrayBuffer()], { type: blob.type || fallbackType });
}

export function runtimeUrls(resourceBaseUrl: string): { script: string; wasm: string } {
  return {
    script: `${resourceBaseUrl}/static/sdk/runtime/OpenVmanAvatarRuntime.js`,
    wasm: `${resourceBaseUrl}/static/sdk/runtime/OpenVmanAvatarRuntime.wasm`,
  };
}

export function characterUrls(
  assetsBaseUrl: string,
  characterId: string,
): { data: string; video: string } {
  const base = `${assetsBaseUrl}/${encodeURIComponent(characterId)}`;
  return { data: `${base}/combined_data.json.gz`, video: `${base}/01.webm` };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function withRetry<T>(load: () => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await load();
    } catch (error) {
      if (!isTransientAssetError(error) || attempt >= RETRY_DELAYS_MS.length) throw error;
      await delay(RETRY_DELAYS_MS[attempt]);
    }
  }
}

function pick(files: Map<string, LoadedAsset>, url: string): LoadedAsset {
  const asset = files.get(url);
  if (!asset) throw new Error(`Missing avatar asset ${url}.`);
  return asset;
}

/**
 * Gets the runtime and the character before anything is created on the page,
 * so a network failure leaves nothing behind and init() can simply run again.
 */
export async function loadAvatarAssets(
  resourceBaseUrl: string,
  assetsBaseUrl: string,
  characterId: string,
  useCache: boolean,
): Promise<AvatarAssets> {
  const runtime = runtimeUrls(resourceBaseUrl);
  const character = characterUrls(assetsBaseUrl, characterId);
  const characterGroup = `character:${character.data}`;
  const [runtimeFiles, characterFiles] = await Promise.all([
    withRetry(() => loadAssetGroup(
      { key: `runtime:${resourceBaseUrl}`, urls: [runtime.script, runtime.wasm] },
      { useCache },
    )),
    withRetry(() => loadAssetGroup(
      { key: characterGroup, urls: [character.data, character.video] },
      { useCache },
    )),
  ]);
  const all = [...runtimeFiles.values(), ...characterFiles.values()];
  const video = pick(characterFiles, character.video);
  return {
    characterData: new Uint8Array(await pick(characterFiles, character.data).blob.arrayBuffer()),
    fromCache: all.every((asset) => asset.fromCache),
    runtimeScript: pick(runtimeFiles, runtime.script).blob,
    runtimeScriptUrl: runtime.script,
    runtimeWasm: await pick(runtimeFiles, runtime.wasm).blob.arrayBuffer(),
    runtimeWasmUrl: runtime.wasm,
    video: video.fromCache ? await inMemory(video.blob, "video/webm") : video.blob,
    videoUrl: character.video,
    ...(video.fromCache
      ? {
        reloadVideo: async () => {
          await forgetAssetGroup(characterGroup);
          return downloadAsset(character.video);
        },
      }
      : {}),
  };
}
