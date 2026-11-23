import { OpenVmanAvatarError } from "./errors";

// 檔案與 manifest 都存在嵌入頁面自己網域的 Cache Storage；鍵是一般網址，不會真的被請求。
const CACHE_NAME = "openvman-avatar-assets-v1";
const MANIFEST_PREFIX = "https://openvman-avatar.cache/manifest/";
// 用存檔前先問伺服器（只等標頭）：被拒就不能再顯示。等不到就當作離線，用存檔。
const CHECK_TIMEOUT_MS = 3_000;
const HEADERS_TIMEOUT_MS = 15_000;
// 影片最大十幾 MB，慢的行動網路要一分多鐘。
const BODY_TIMEOUT_MS = 120_000;
const UNUSED_GROUP_MS = 30 * 24 * 60 * 60 * 1000;
const TOUCH_INTERVAL_MS = 24 * 60 * 60 * 1000;
const DENIED_STATUSES = new Set([401, 403, 404]);

export interface AssetGroup {
  /** One manifest per group; files of a group are only ever swapped together. */
  key: string;
  urls: string[];
}

export interface LoadedAsset {
  blob: Blob;
  fromCache: boolean;
}

interface ManifestEntry {
  cacheKey: string;
  contentLength: string;
  lastModified: string;
}

interface Manifest {
  files: Record<string, ManifestEntry>;
  usedAt?: number;
}

/** Network failure, timeout, 5xx or a response that is not the file (portal page, redirect). */
export class TransientAssetError extends OpenVmanAvatarError {
  constructor(message: string) {
    super("RESOURCE_LOAD_FAILED", message);
  }
}

/** The server refused the file: access was revoked or the file is gone. */
class AssetDeniedError extends OpenVmanAvatarError {
  constructor(message: string) {
    super("RESOURCE_LOAD_FAILED", message);
  }
}

export function isTransientAssetError(error: unknown): boolean {
  return error instanceof TransientAssetError;
}

interface PendingResponse {
  controller: AbortController;
  response: Response;
}

async function openCache(): Promise<Cache | null> {
  try {
    if (typeof caches === "undefined") return null;
    return await caches.open(CACHE_NAME);
  } catch {
    // 非 https 頁面、隱私模式或使用者封鎖網站資料時沒有 Cache Storage，照舊走網路。
    return null;
  }
}

function manifestKey(groupKey: string): string {
  return `${MANIFEST_PREFIX}${encodeURIComponent(groupKey)}`;
}

function header(response: Response, name: string): string {
  return response.headers?.get?.(name) ?? "";
}

function fileKey(url: string, response: Response): string {
  // 版本由內容決定，同一版重寫會蓋同一把鍵，寫一半失敗也不會留下另一份孤兒檔。
  const version = `${header(response, "last-modified")}|${header(response, "content-length")}`;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}openvman-cache=${encodeURIComponent(version)}`;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Fetches *url* and waits for its headers only; the body is read later or aborted. */
async function requestHeaders(
  url: string,
  timeoutMs: number,
  { revalidate = false }: { revalidate?: boolean } = {},
): Promise<PendingResponse> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    // 檢查存檔時一定要問到伺服器：瀏覽器的 HTTP 快取（max-age）會直接回 200，看不到撤銷。
    // no-cache 讓瀏覽器帶條件請求，沒變時伺服器回 304，也不必重抓。
    response = await fetch(
      url,
      revalidate ? { cache: "no-cache", signal: controller.signal } : { signal: controller.signal },
    );
  } catch (error) {
    throw new TransientAssetError(`Unable to load ${url}: ${errorText(error)}.`);
  } finally {
    window.clearTimeout(timer);
  }
  const reject = (error: OpenVmanAvatarError): never => {
    controller.abort();
    throw error;
  };
  const status = response.status;
  if (DENIED_STATUSES.has(status)) {
    reject(new AssetDeniedError(`Avatar asset request failed with HTTP ${status}: ${url}.`));
  }
  if (status >= 500 || status === 408 || status === 429) {
    reject(new TransientAssetError(`Avatar asset request failed with HTTP ${status}: ${url}.`));
  }
  if (!response.ok || status !== 200) {
    reject(new OpenVmanAvatarError(
      "RESOURCE_LOAD_FAILED",
      `Avatar asset request failed with HTTP ${status}: ${url}.`,
    ));
  }
  // 登入頁、captive portal、網站的 SPA 首頁都會回 200 HTML；那不是這個檔，不能存進去蓋掉好的版本。
  if (response.redirected || header(response, "content-type").toLowerCase().startsWith("text/html")) {
    reject(new TransientAssetError(`Avatar asset ${url} returned a page instead of the file.`));
  }
  return { controller, response };
}

async function readBody(url: string, pending: PendingResponse): Promise<Blob> {
  const timer = window.setTimeout(() => pending.controller.abort(), BODY_TIMEOUT_MS);
  try {
    return await pending.response.blob();
  } catch (error) {
    // 下載到一半斷線也是暫時性的，交給呼叫端重試。
    throw new TransientAssetError(`Download of ${url} was interrupted: ${errorText(error)}.`);
  } finally {
    window.clearTimeout(timer);
  }
}

async function readManifest(cache: Cache, groupKey: string): Promise<Manifest | null> {
  try {
    const response = await cache.match(manifestKey(groupKey));
    if (!response) return null;
    const manifest = (await response.json()) as Manifest;
    return manifest && typeof manifest.files === "object" ? manifest : null;
  } catch {
    return null;
  }
}

async function readFiles(
  cache: Cache,
  group: AssetGroup,
  manifest: Manifest,
): Promise<Map<string, LoadedAsset> | null> {
  const loaded = new Map<string, LoadedAsset>();
  for (const url of group.urls) {
    const entry = manifest.files[url];
    const response = entry ? await cache.match(entry.cacheKey) : undefined;
    if (!response) return null;
    loaded.set(url, { blob: await response.blob(), fromCache: true });
  }
  return loaded;
}

async function readCachedGroup(
  cache: Cache,
  group: AssetGroup,
): Promise<{ files: Map<string, LoadedAsset>; manifest: Manifest } | null> {
  // 另一個分頁可能剛換版、刪掉舊檔：讀不到就重讀一次 manifest。
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const manifest = await readManifest(cache, group.key);
    if (!manifest) return null;
    const files = await readFiles(cache, group, manifest).catch(() => null);
    if (files) return { files, manifest };
  }
  return null;
}

async function purgeGroup(cache: Cache, groupKey: string): Promise<void> {
  const manifest = await readManifest(cache, groupKey);
  await cache.delete(manifestKey(groupKey));
  for (const entry of Object.values(manifest?.files ?? {})) {
    await cache.delete(entry.cacheKey);
  }
}

async function writeGroup(
  cache: Cache,
  group: AssetGroup,
  fresh: Map<string, { blob: Blob; response: Response }>,
  previous: Manifest | null,
): Promise<void> {
  const files: Record<string, ManifestEntry> = { ...(previous?.files ?? {}) };
  for (const [url, { blob, response }] of fresh) {
    const cacheKey = fileKey(url, response);
    await cache.put(cacheKey, new Response(blob, {
      headers: { "content-type": header(response, "content-type") || blob.type },
    }));
    files[url] = {
      cacheKey,
      contentLength: header(response, "content-length"),
      lastModified: header(response, "last-modified"),
    };
  }
  // manifest 最後才寫：寫到一半被關掉時，讀取仍指向完整的舊版。
  await writeManifest(cache, group.key, { files, usedAt: Date.now() });
  for (const url of fresh.keys()) {
    const old = previous?.files[url];
    if (old && old.cacheKey !== files[url].cacheKey) await cache.delete(old.cacheKey);
  }
}

async function writeManifest(cache: Cache, groupKey: string, manifest: Manifest): Promise<void> {
  await cache.put(manifestKey(groupKey), new Response(JSON.stringify(manifest), {
    headers: { "content-type": "application/json" },
  }));
}

/**
 * Drops groups unused for 30 days, files included: a page that switched
 * characters never checks the old one again. Files no manifest points to are
 * left alone, because another group may be between writing its files and its
 * manifest; a failed write leaves at most one file per URL (keys are by version).
 */
async function prune(cache: Cache): Promise<void> {
  const now = Date.now();
  for (const request of await cache.keys()) {
    if (!request.url.startsWith(MANIFEST_PREFIX)) continue;
    const response = await cache.match(request);
    const manifest = response ? ((await response.json().catch(() => null)) as Manifest | null) : null;
    if (manifest?.files && now - (manifest.usedAt ?? 0) <= UNUSED_GROUP_MS) continue;
    await cache.delete(request);
    for (const entry of Object.values(manifest?.files ?? {})) await cache.delete(entry.cacheKey);
  }
}

async function touch(cache: Cache, group: AssetGroup, manifest: Manifest): Promise<void> {
  if (Date.now() - (manifest.usedAt ?? 0) < TOUCH_INTERVAL_MS) return;
  await writeManifest(cache, group.key, { ...manifest, usedAt: Date.now() });
  await prune(cache);
}

function unchanged(response: Response, entry: ManifestEntry | undefined): boolean {
  const lastModified = header(response, "last-modified");
  return Boolean(
    entry
    && lastModified
    && lastModified === entry.lastModified
    && header(response, "content-length") === entry.contentLength,
  );
}

/**
 * Asks the server about every stored file before the copy is shown. Throws
 * AssetDeniedError when it refuses one; returns null when it cannot be
 * reached in time (offline: show the copy); otherwise returns the responses
 * of changed files, whose bodies are still unread.
 */
async function checkGroup(
  group: AssetGroup,
  manifest: Manifest,
): Promise<Map<string, PendingResponse> | null> {
  const results = await Promise.allSettled(
    group.urls.map((url) => requestHeaders(url, CHECK_TIMEOUT_MS, { revalidate: true })),
  );
  const abortAll = (): void => {
    for (const result of results) {
      if (result.status === "fulfilled") result.value.controller.abort();
    }
  };
  const failures = results.flatMap((result) => (result.status === "rejected" ? [result.reason] : []));
  if (failures.length) {
    abortAll();
    const denied = failures.find((error) => error instanceof AssetDeniedError);
    if (denied) throw denied;
    if (failures.every(isTransientAssetError)) return null;
    throw failures[0];
  }
  const changed = new Map<string, PendingResponse>();
  group.urls.forEach((url, index) => {
    const pending = (results[index] as PromiseFulfilledResult<PendingResponse>).value;
    if (unchanged(pending.response, manifest.files[url])) {
      pending.controller.abort();
    } else {
      changed.set(url, pending);
    }
  });
  return changed;
}

async function updateGroup(
  cache: Cache,
  group: AssetGroup,
  manifest: Manifest,
  changed: Map<string, PendingResponse>,
): Promise<void> {
  const fresh = new Map<string, { blob: Blob; response: Response }>();
  for (const [url, pending] of changed) {
    fresh.set(url, { blob: await readBody(url, pending), response: pending.response });
  }
  // 下載期間另一個分頁可能因 401／403／404 清掉了這組；不能再寫回去。
  if (!(await readManifest(cache, group.key))) return;
  await writeGroup(cache, group, fresh, manifest);
}

/**
 * Returns every file of *group*. A stored copy is used only after the server
 * has not refused it (or cannot be reached); changed files are downloaded in
 * the background for the next visit. Cache errors never fail the load; they
 * only turn caching off.
 */
export async function loadAssetGroup(
  group: AssetGroup,
  { useCache }: { useCache: boolean },
): Promise<Map<string, LoadedAsset>> {
  const cache = useCache ? await openCache() : null;
  const stored = cache ? await readCachedGroup(cache, group).catch(() => null) : null;
  if (cache && stored) {
    let changed: Map<string, PendingResponse> | null;
    try {
      changed = await checkGroup(group, stored.manifest);
    } catch (error) {
      if (error instanceof AssetDeniedError) await purgeGroup(cache, group.key).catch(() => {});
      throw error;
    }
    if (changed?.size) {
      void updateGroup(cache, group, stored.manifest, changed).catch(() => {});
    } else {
      void touch(cache, group, stored.manifest).catch(() => {});
    }
    return stored.files;
  }

  const fresh = new Map<string, { blob: Blob; response: Response }>();
  try {
    for (const url of group.urls) {
      const pending = await requestHeaders(url, HEADERS_TIMEOUT_MS);
      fresh.set(url, { blob: await readBody(url, pending), response: pending.response });
    }
  } catch (error) {
    if (cache && error instanceof AssetDeniedError) {
      await purgeGroup(cache, group.key).catch(() => {});
    }
    throw error;
  }
  if (cache) {
    void (async () => {
      await writeGroup(cache, group, fresh, await readManifest(cache, group.key));
    })().catch(() => {});
  }
  return new Map(
    [...fresh].map(([url, { blob }]) => [url, { blob, fromCache: false }]),
  );
}
