#!/usr/bin/env node
/**
 * Real SDK smoke/E2E test; run after the motion experiment is deployed.
 * MOTION_TEST_USERNAME and MOTION_TEST_PASSWORD are required.
 * BASE_URL defaults to https://localhost:8787.
 * MOTION_ARTIFACT_DIR defaults to /tmp/openvman-avatar-motion-<timestamp>.
 * MOTION_CACHE_FOCUSED_ONLY=1 runs mobile cache, decoder fallback and preload failure tests.
 * This script intentionally never sends chat messages or changes settings.
 */
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { delimiter, dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';

const require = createRequire(import.meta.url);
const runFile = promisify(execFile);
function loadPlaywright() {
  try { return require('playwright-core'); } catch { /* Global CLI fallback below. */ }
  const candidates = [
    process.env.MOTION_PLAYWRIGHT_PACKAGE,
    join(dirname(process.execPath), '..', 'lib', 'node_modules', 'agent-browser', 'package.json'),
    ...(process.env.PATH ?? '').split(delimiter).map((entry) =>
      join(entry, '..', 'lib', 'node_modules', 'agent-browser', 'package.json')),
    '/usr/local/lib/node_modules/agent-browser/package.json',
    '/usr/lib/node_modules/agent-browser/package.json',
  ].filter(Boolean);
  for (const candidate of candidates) {
    try { return createRequire(resolve(candidate))('playwright-core'); } catch { /* Try next installation. */ }
  }
  throw new Error('找不到 playwright-core；可用 MOTION_PLAYWRIGHT_PACKAGE 指定 agent-browser/package.json。');
}

const baseURL = new URL(process.env.BASE_URL ?? 'https://localhost:8787');
const demoURL = new URL('/experiments/avatar-motion/', baseURL).href;
const artifactDir = resolve(process.env.MOTION_ARTIFACT_DIR
  ?? `/tmp/openvman-avatar-motion-${new Date().toISOString().replaceAll(':', '-')}`);
const username = process.env.MOTION_TEST_USERNAME;
const password = process.env.MOTION_TEST_PASSWORD;
const readyTimeout = Number(process.env.MOTION_READY_TIMEOUT_MS ?? 180000);
const phaseTimeout = Number(process.env.MOTION_PHASE_TIMEOUT_MS ?? 45000);
const cycleTimeout = Number(process.env.MOTION_CYCLE_TIMEOUT_MS ?? 60000);
const LOOP_STATES = ['idle', 'thinking', 'speaking'];
const ONE_SHOT_STATES = ['greeting', 'bye'];
const ALL_STATES = [...LOOP_STATES, ...ONE_SHOT_STATES];
const EXPECTED_SEGMENTS = {
  idle: { start: 0, end: 8 }, speaking: { start: 0, end: 8 },
  thinking: { start: 8, end: 16 }, greeting: { start: 16, end: 24 }, bye: { start: 24, end: 32 },
};
const cacheFocusedOnly = process.env.MOTION_CACHE_FOCUSED_ONLY === '1';
const report = {
  startedAt: new Date().toISOString(), baseURL: baseURL.origin, demoURL,
  artifactDir, mode: cacheFocusedOnly ? 'cache-focused' : 'full', passed: false, checks: [], snapshots: [], frames: [],
  requests: [], forbiddenWrites: [], failedRequests: [], pageErrors: [], consoleErrors: [],
  limitations: ['未以實體喇叭或麥克風量測聲音；SDK 音訊以完整示範及錄影留證。'],
};
let browser;
let context;
let page;
let video;
let phase = 'setup';
let runtimeBaseline;
let runtimeRequests = [];

function isCharacterResource({ path, protocol }) {
  return ['http:', 'https:'].includes(protocol)
    && (path.startsWith('/static/characters/') || /\.wasm(?:[./]|$)/i.test(path)
      || /\/api\/.*characters?\//i.test(path));
}

function assertCacheShape(value, label) {
  const cache = value.videoCache;
  assert.ok(cache && typeof cache === 'object', `${label}: 沒有 videoCache 可觀察資料`);
  for (const field of ['hits', 'misses', 'entries', 'maxEntries', 'pending']) {
    assert.ok(Number.isInteger(cache[field]) && cache[field] >= 0, `${label}: videoCache.${field} 無效`);
  }
  // entries counts standby videos; the separately active video is excluded.
  const maximum = value.deviceMemory && value.deviceMemory <= 4 ? 2 : 3;
  assert.ok(cache.maxEntries >= 1 && cache.maxEntries <= maximum, `${label}: standby 快取上限超出 ${maximum}`);
  assert.ok(cache.entries <= cache.maxEntries, `${label}: standby 快取數量超出上限`);
}

function assertSourceBundle(value, label) {
  assert.equal(value.source, 'hciot-v1', `${label}: 沒有使用新提供的 hciot bundle`);
  assert.ok(value.duration >= 31.9, `${label}: 合併影片未保留四段完整時間軸`);
  for (const name of ALL_STATES) {
    const segment = value.segments[name];
    assert.ok(segment && Number.isFinite(segment.start) && Number.isFinite(segment.end)
      && segment.end <= value.duration + 0.1, `${label}/${name}: segment 無效`);
    assert.ok(Math.abs(segment.start - EXPECTED_SEGMENTS[name].start) < 0.08
      && Math.abs(segment.end - EXPECTED_SEGMENTS[name].end) < 0.08,
    `${label}/${name}: 沒有沿用正確原始合併時間軸`);
  }
}

function assertTransition(entry, label, expectHit = false) {
  assert.ok(entry, `${label}: 沒有完成的切換紀錄`);
  assert.equal(typeof entry.cacheHit, 'boolean', `${label}: 切換紀錄缺少 cacheHit`);
  if (expectHit) assert.equal(entry.cacheHit, true, `${label}: 已準備的 segment 未命中快取`);
  for (const field of ['prepareMs', 'renderMs', 'ms']) {
    assert.ok(Number.isFinite(entry[field]) && entry[field] >= 0, `${label}: ${field} 不是有限非負值`);
  }
  assert.ok(entry.ms + 2 >= Math.max(entry.prepareMs, entry.renderMs), `${label}: 總交接時間未包含準備或繪圖時間`);
}

function assertRuntimeStable(value, label) {
  if (!runtimeBaseline) return;
  assert.equal(value.runtime.documentId, runtimeBaseline.runtime.documentId, `${label}: 切換造成文件重載`);
  assert.equal(value.runtime.sdkInitCalls, 1, `${label}: 切換或循環重啟 SDK`);
  assert.equal(value.runtime.wasmCalls, runtimeBaseline.runtime.wasmCalls, `${label}: 切換或循環重新初始化 WASM`);
  assert.deepEqual(runtimeRequests.filter(isCharacterResource), runtimeBaseline.resources,
    `${label}: ready 後重新請求角色資料、影片或 WASM`);
  assert.equal(value.media?.source, runtimeBaseline.source, `${label}: 切換或循環更換了原始影片 blob`);
  assert.deepEqual(value.segments, runtimeBaseline.segments, `${label}: 快取改變了原 segment 時間軸`);
  assert.equal(value.source, 'hciot-v1', `${label}: 切換回舊角色素材`);
  assert.ok(value.frameCount >= runtimeBaseline.frameCount, `${label}: vendor 繪圖計數遭重設`);
  if (runtimeBaseline.allowNoCache) assert.equal(value.videoCache, null, `${label}: 降級後仍保留失敗的快取`);
  else assertCacheShape(value, label);
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
function check(name, details = {}) {
  report.checks.push({ name, passed: true, ...details });
  console.log('[PASS] ' + name);
}
async function snapshot(label) {
  const value = await page.evaluate(() => {
    const video = window.characterVideo;
    return {
      ...window.motionDemo.snapshot(),
      media: video ? {
        currentTime: video.currentTime, paused: video.paused, readyState: video.readyState,
        source: video.currentSrc || video.src,
      } : null,
      runtime: window.__motionE2eRuntimeProbe ? { ...window.__motionE2eRuntimeProbe } : null,
      deviceMemory: navigator.deviceMemory ?? null,
    };
  });
  report.snapshots.push({ label, at: new Date().toISOString(), ...value });
  assert.equal(value.ready, true, `${label}: SDK 尚未就緒`);
  assert.deepEqual(value.errors, [], `${label}: demo 回報錯誤`);
  assertRuntimeStable(value, label);
  return value;
}
async function settled(state) {
  await page.waitForFunction((expected) => {
    const current = window.motionDemo.snapshot();
    return current.ready && current.state === expected && !current.transitioning;
  }, state, { timeout: phaseTimeout });
}

async function cachePrepared() {
  await page.waitForFunction(() => window.motionDemo.snapshot().videoCache?.pending === 0,
    null, { timeout: phaseTimeout });
}

async function watchNetwork(target, label) {
  const cdp = await target.context().newCDPSession(target);
  const requests = new Map();
  await cdp.send('Network.enable');
  cdp.on('Network.requestWillBeSent', ({ requestId, request, type }) => {
    const url = new URL(request.url);
    requests.set(requestId, { path: url.pathname, method: request.method, type });
  });
  cdp.on('Network.loadingFailed', ({ requestId, errorText, canceled, blockedReason, corsErrorStatus, type }) => {
    (report.networkLoadingFailures ??= []).push({
      context: label, requestId, ...requests.get(requestId), type,
      errorText, canceled, blockedReason, corsErrorStatus,
    });
  });
}

async function visibleStateLabel(label) {
  const target = page.locator('#stage-state');
  await target.scrollIntoViewIfNeeded();
  const result = await target.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const x = bounds.left + bounds.width / 2;
    const y = bounds.top + bounds.height / 2;
    const hit = document.elementFromPoint(x, y);
    const style = getComputedStyle(element);
    return {
      text: element.textContent, visible: bounds.width > 0 && bounds.height > 0
        && style.visibility === 'visible' && Number(style.opacity) > 0,
      centerHitsLabel: hit === element || element.contains(hit),
      hitTag: hit?.tagName ?? null, hitId: hit?.id ?? null,
    };
  });
  assert.ok(result.visible && result.centerHitsLabel,
    `${label}: 狀態標籤被 SDK 或其他圖層蓋住：${JSON.stringify(result)}`);
  return result;
}

// A compositor screenshot still sees a WebGL canvas when its drawing buffer is
// discarded. Keep the independent canvas readback as evidence of real alpha.
async function frame(label) {
  const stateLabel = await visibleStateLabel(label);
  // The held-frame overlay retains layout when opacity is zero. Selecting the
  // largest :visible canvas can therefore inspect the transition buffer.
  const target = page.locator('#canvas_video');
  assert.equal(await target.count(), 1, `${label}: 找不到唯一 SDK canvas_video`);
  assert.ok(await target.isVisible(), `${label}: SDK canvas 不可見`);
  const png = await target.screenshot({ timeout: phaseTimeout });
  const raw = await target.evaluate((canvas) => {
    const scratch = document.createElement('canvas');
    scratch.width = 64; scratch.height = 64;
    try {
      const ctx = scratch.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(canvas, 0, 0, 64, 64);
      const pixels = ctx.getImageData(0, 0, 64, 64).data;
      let opaque = 0; let lit = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] > 16) opaque++;
        if (pixels[i + 3] > 16 && Math.max(pixels[i], pixels[i + 1], pixels[i + 2]) > 20) lit++;
      }
      return { opaque, lit, total: pixels.length / 4 };
    } catch (error) { return { error: error.message }; }
  });
  const visible = await page.evaluate(async (dataURL) => {
    const image = new Image();
    image.src = dataURL;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = 64; canvas.height = 64;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(image, 0, 0, 64, 64);
    const pixels = ctx.getImageData(0, 0, 64, 64).data;
    let lit = 0; let sum = 0; let squared = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      const value = (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3;
      if (value > 20) lit++;
      sum += value; squared += value * value;
    }
    const total = pixels.length / 4;
    return { lit, total, mean: sum / total, variance: squared / total - (sum / total) ** 2 };
  }, `data:image/png;base64,${png.toString('base64')}`);
  const result = { label, raw, visible, stateLabel };
  report.frames.push(result);
  assert.ok(!raw.error, `${label}: canvas 無法讀回：${raw.error}`);
  assert.ok(raw.opaque > raw.total * 0.01, `${label}: canvas 沒有實際非透明幀`);
  assert.ok(visible.lit > visible.total * 0.01 && visible.variance > 2,
    `${label}: canvas 全黑或只有單色背景`);
  return result;
}

async function monitor(label, duration, { expectedState, untilCycleDone = false, untilState } = {}) {
  const deadline = Date.now() + duration;
  const states = new Set();
  let nextFrame = 0;
  while (Date.now() < deadline) {
    const value = await snapshot(label);
    states.add(value.state);
    if (expectedState) assert.equal(value.state, expectedState, `${label}: 被過期工作切換狀態`);
    if (Date.now() >= nextFrame) {
      await frame(label);
      nextFrame = Date.now() + 850;
    }
    if (untilState && value.state === untilState && !value.transitioning) return [...states];
    if (untilCycleDone) {
      const cycle = await page.evaluate(() => window.__motionE2eCycle);
      if (cycle.done) {
        assert.equal(cycle.error, null, `${label}: runCycle 失敗：${cycle.error}`);
        return [...states];
      }
    }
    await sleep(120);
  }
  assert.ok(!untilCycleDone, `${label}: runCycle 未在 ${duration}ms 內結束`);
  assert.ok(!untilState, `${label}: 未在 ${duration}ms 內回到 ${untilState}`);
  return [...states];
}

async function verifyOneShot(state, label) {
  await page.evaluate((name) => window.motionDemo.setState(name), state);
  await settled(state);
  const before = await snapshot(`${label}-start`);
  const segment = before.segments[state];
  assert.ok(before.media.currentTime >= segment.start - 0.25
    && before.media.currentTime < segment.start + 1, `${label}: one-shot 沒有從該動作開頭開始`);
  await page.evaluate((state) => {
    const probe = window.__motionE2eOneShot = {
      state, started: performance.now(), maxTime: -1, samples: 0, returned: false,
    };
    const tick = () => {
      const value = window.motionDemo.snapshot();
      if (value.state === state && !value.transitioning) {
        probe.maxTime = Math.max(probe.maxTime, window.characterVideo.currentTime);
        probe.samples += 1;
      } else if (value.state === 'idle' && !value.transitioning) {
        probe.returned = true;
        probe.elapsedMs = performance.now() - probe.started;
        return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, state);
  await frame(`${label}-start`);
  await page.screenshot({ path: join(artifactDir, `${label}-start.png`) });
  const states = await monitor(label, Math.max(phaseTimeout, (segment.end - segment.start) * 1000 + 10000), { untilState: 'idle' });
  const after = await snapshot(`${label}-completed`);
  await page.waitForFunction(() => window.__motionE2eOneShot.returned, null, { timeout: phaseTimeout });
  const probe = await page.evaluate(() => ({ ...window.__motionE2eOneShot }));
  assert.ok(states.includes(state) && states.includes('idle'), `${label}: 沒有完整動作到待機的狀態交接`);
  assert.ok(probe.returned && probe.samples > 10, `${label}: 無法觀察到實際 one-shot 播放`);
  assert.ok(probe.maxTime >= segment.end - 0.35, `${label}: 動作未播到尾段便回待機`);
  assert.ok(probe.elapsedMs >= (segment.end - segment.start - 0.75) * 1000, `${label}: 動作被過早截斷`);
  assert.ok(after.frameCount > before.frameCount, `${label}: 動作期間 canvas 沒有持續繪圖`);
  assert.ok(!after.transitions.slice(before.transitions.length)
    .some((entry) => entry.state === state && entry.reason === 'loop'), `${label}: one-shot 被錯誤循環`);
  await monitor(`${label}-stays-idle`, 450, { expectedState: 'idle' });
  await page.screenshot({ path: join(artifactDir, `${label}-completed.png`) });
  check(`${label}-finishes-entire-motion-and-returns-idle`, { probe, states });
}

async function startCycle() {
  await page.evaluate(() => {
    window.__motionE2eCycle = { done: false, error: null };
    Promise.resolve().then(() => window.motionDemo.runCycle()).then(
      () => { window.__motionE2eCycle.done = true; },
      (error) => { window.__motionE2eCycle = { done: true, error: String(error) }; },
    );
  });
}

async function protectContext(target) {
  await target.route('**/*', async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname;
    const write = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    const allowed = method === 'POST' && [
      '/api/v1/auth/admin-login', '/api/v1/tts/stream',
      '/api/v1/tts', '/v1/audio/speech', '/api/v1/audio/speech',
    ].includes(path);
    if (write && !allowed) {
      report.forbiddenWrites.push({ method, path });
      await route.abort('blockedbyclient');
    } else await route.continue();
  });
  // The isolated sample has no websocket requirement. Block before connecting,
  // so a regression cannot create a chat turn through a websocket instead.
  await target.routeWebSocket('**/*', (socket) => {
    report.forbiddenWrites.push({ method: 'WEBSOCKET', path: new URL(socket.url()).pathname });
    socket.close({ code: 1008, reason: 'Isolated motion test forbids websocket writes' });
  });
}

async function focusedCacheScenario(name, injectStandbyFailure = false) {
  phase = name;
  if (context) await context.close();
  context = undefined;
  page = undefined;
  runtimeBaseline = undefined;
  runtimeRequests = [];
  const details = { name, requests: runtimeRequests, states: [] };
  (report.focusedContexts ??= []).push(details);
  context = await browser.newContext({
    ignoreHTTPSErrors: true, viewport: { width: 375, height: 960 },
    isMobile: true, hasTouch: true, deviceScaleFactor: 1, serviceWorkers: 'block',
  });
  await protectContext(context);
  const login = await context.request.post(new URL('/api/v1/auth/admin-login', baseURL).href, {
    data: { username, password },
  });
  assert.ok(login.ok(), `${name}: 登入失敗 HTTP ${login.status()}`);
  page = await context.newPage();
  await watchNetwork(page, name);
  page.on('request', (request) => {
    const url = new URL(request.url());
    runtimeRequests.push({ method: request.method(), path: url.pathname, protocol: url.protocol });
  });
  page.on('pageerror', (error) => report.pageErrors.push(`${name}: ${error.message}`));
  await page.addInitScript(({ injectStandbyFailure }) => {
    Object.defineProperty(navigator, 'deviceMemory', { configurable: true, get: () => 2 });
    const probe = window.__motionE2eRuntimeProbe = {
      documentId: `${Date.now()}-${Math.random()}`, sdkInitCalls: 0, wasmCalls: 0, standbyLoadFailures: 0,
    };
    for (const name of ['instantiate', 'instantiateStreaming']) {
      const original = WebAssembly[name];
      if (original) WebAssembly[name] = function (...args) {
        probe.wasmCalls += 1;
        return Reflect.apply(original, this, args);
      };
    }
    if (injectStandbyFailure) {
      const load = HTMLMediaElement.prototype.load;
      HTMLMediaElement.prototype.load = function (...args) {
        // Only the lab's connected, hidden standby decoder is faulted. The
        // vendor's active video and its original SDK load remain untouched.
        if (this instanceof HTMLVideoElement && this !== window.characterVideo
            && this.hidden && this.isConnected && this.src.startsWith('blob:')) {
          probe.standbyLoadFailures += 1;
          queueMicrotask(() => this.dispatchEvent(new Event('error')));
          return;
        }
        return Reflect.apply(load, this, args);
      };
    }
  }, { injectStandbyFailure });
  await page.goto(demoURL, { waitUntil: 'domcontentloaded', timeout: readyTimeout });
  await page.waitForFunction(() => Boolean(window.motionDemo), null, { timeout: readyTimeout });
  await page.evaluate(() => {
    const sdk = window.OpenVmanAvatar;
    if (!sdk?.init) throw new Error('無法觀察手機 SDK init 次數');
    const init = sdk.init;
    window.OpenVmanAvatar = {
      ...sdk,
      init(...args) {
        window.__motionE2eRuntimeProbe.sdkInitCalls += 1;
        return Reflect.apply(init, sdk, args);
      },
    };
  });
  await page.waitForFunction(() => window.motionDemo.snapshot().access === 'available', null, { timeout: phaseTimeout });
  await page.getByRole('button', { name: '載入測試角色', exact: true }).click();
  await page.evaluate(async (timeout) => {
    await Promise.race([
      window.motionDemo.ready,
      new Promise((_, reject) => setTimeout(() => reject(new Error('focused SDK ready timeout')), timeout)),
    ]);
  }, readyTimeout);
  await settled('idle');
  const initial = await snapshot(`${name}-ready`);
  assertSourceBundle(initial, name);
  assert.equal(initial.deviceMemory, 2, `${name}: 未套用低記憶體模擬`);
  assert.ok(await page.evaluate(() => navigator.maxTouchPoints > 0), `${name}: 未啟用觸控模擬`);
  assert.equal(initial.runtime.sdkInitCalls, 1, `${name}: SDK init 次數不為一`);
  assert.ok(initial.media?.source.startsWith('blob:'), `${name}: 未沿用預載影片 blob`);
  assert.ok(initial.frameCount > 0, `${name}: SDK 沒有繪出真實影片`);
  if (injectStandbyFailure) {
    assert.ok(initial.runtime.standbyLoadFailures > 0, '未實際觸發待命影片解碼錯誤');
    assert.equal(initial.videoCache, null, '待命影片失敗後沒有降級為單一 video');
  } else {
    assertCacheShape(initial, name);
    assert.equal(initial.videoCache.maxEntries, 2, '低記憶體裝置必須限制最多兩個 standby');
  }
  runtimeBaseline = {
    runtime: initial.runtime, resources: runtimeRequests.filter(isCharacterResource),
    source: initial.media.source, segments: initial.segments, frameCount: initial.frameCount,
    allowNoCache: injectStandbyFailure,
  };
  details.baseline = runtimeBaseline;
  check(`${name}-real-sdk-ready`, { cache: initial.videoCache, injectedFailures: initial.runtime.standbyLoadFailures });
  const missesBefore = initial.videoCache?.misses;
  for (const state of LOOP_STATES) {
    phase = `${name}-${state}`;
    await page.evaluate((next) => window.motionDemo.setState(next), state);
    await settled(state);
    if (!injectStandbyFailure) await cachePrepared();
    const before = await snapshot(`${name}-${state}-start`);
    await monitor(`${name}-${state}-render`, 400, { expectedState: state });
    await page.waitForFunction(({ state, loops }) => {
      const current = window.motionDemo.snapshot();
      return current.state === state && current.loops > loops && !current.transitioning;
    }, { state, loops: before.loops }, { timeout: phaseTimeout });
    if (!injectStandbyFailure) await cachePrepared();
    await frame(`${name}-${state}-loop`);
    const after = await snapshot(`${name}-${state}-loop`);
    assert.ok(after.frameCount > before.frameCount, `${name}/${state}: 循環沒有持續繪圖`);
    assert.ok(after.media.currentTime >= initial.segments[state].start - 0.25
      && after.media.currentTime <= initial.segments[state].end + 0.25,
    `${name}/${state}: 實際播放時間不在原 segment`);
    const transition = after.transitions.filter((entry) => entry.state === state && entry.reason === 'loop').at(-1);
    assertTransition(transition, `${name}/${state}`, !injectStandbyFailure);
    if (!injectStandbyFailure) {
      assert.ok(after.videoCache.hits > before.videoCache.hits, `${name}/${state}: 循環沒有命中快取`);
      assert.equal(after.videoCache.misses, before.videoCache.misses, `${name}/${state}: 已準備循環發生 miss`);
    }
    await page.screenshot({ path: join(artifactDir, `${name}-${state}-375.png`), fullPage: true });
    details.states.push({ state, transition, cache: after.videoCache });
    check(`${name}-${state}-loops-and-renders`, { cache: after.videoCache, transition });
  }
  for (const state of ONE_SHOT_STATES) await verifyOneShot(state, `${name}-${state}`);
  const final = await snapshot(`${name}-final`);
  if (!injectStandbyFailure) {
    assert.ok(final.videoCache.misses > missesBefore, '兩個 standby 缺少第三個 segment 時未記錄 cache miss');
    check('mobile-cache-miss-is-local-and-bounded', { beforeMisses: missesBefore, cache: final.videoCache });
  }
  const layout = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth, bodyWidth: document.body.scrollWidth,
  }));
  assert.ok(layout.documentWidth <= layout.viewport + 1 && layout.bodyWidth <= layout.viewport + 1, `${name}: 375 手機模擬水平溢出`);
  assertRuntimeStable(final, name);
  check(`${name}-no-sdk-restart-or-character-refetch`, {
    sdkInitCalls: final.runtime.sdkInitCalls, wasmCalls: final.runtime.wasmCalls,
    requestsAtReady: runtimeBaseline.resources.length,
    requestsAtEnd: runtimeRequests.filter(isCharacterResource).length,
  });
  await context.close();
  context = undefined;
  page = undefined;
  runtimeBaseline = undefined;
}

async function failedPreloadScenario() {
  phase = 'preload-failure-before-sdk-init';
  runtimeBaseline = undefined;
  if (context) await context.close();
  context = await browser.newContext({
    ignoreHTTPSErrors: true, viewport: { width: 375, height: 960 }, serviceWorkers: 'block',
  });
  await protectContext(context);
  let failedFetches = 0;
  await context.route('**/motion-lab/*/01.webm*', async (route) => {
    // Fail only this isolated context's whole-file preload, never the SDK's
    // media element or any successful-path scenario.
    if (route.request().resourceType() === 'fetch') {
      failedFetches += 1;
      await route.abort('failed');
    } else await route.fallback();
  });
  const login = await context.request.post(new URL('/api/v1/auth/admin-login', baseURL).href, {
    data: { username, password },
  });
  assert.ok(login.ok(), `預載失敗測試登入失敗：HTTP ${login.status()}`);
  page = await context.newPage();
  await watchNetwork(page, 'preload-failure');
  const requests = [];
  report.preloadFailureRequests = requests;
  page.on('request', (request) => requests.push({
    path: new URL(request.url()).pathname, type: request.resourceType(),
  }));
  page.on('pageerror', (error) => report.pageErrors.push(`preload-failure: ${error.message}`));
  await page.addInitScript(() => {
    const probe = window.__motionE2ePreloadProbe = { sdkInitCalls: 0, wasmCalls: 0 };
    for (const name of ['instantiate', 'instantiateStreaming']) {
      const original = WebAssembly[name];
      if (original) WebAssembly[name] = function (...args) {
        probe.wasmCalls += 1;
        return Reflect.apply(original, this, args);
      };
    }
  });
  await page.goto(demoURL, { waitUntil: 'domcontentloaded', timeout: readyTimeout });
  await page.waitForFunction(() => Boolean(window.motionDemo), null, { timeout: readyTimeout });
  await page.evaluate(() => {
    const sdk = window.OpenVmanAvatar;
    if (!sdk?.init) throw new Error('無法觀察預載失敗 SDK init 次數');
    const init = sdk.init;
    window.OpenVmanAvatar = {
      ...sdk,
      init(...args) {
        window.__motionE2ePreloadProbe.sdkInitCalls += 1;
        return Reflect.apply(init, sdk, args);
      },
    };
  });
  await page.waitForFunction(() => window.motionDemo.snapshot().access === 'available', null, { timeout: phaseTimeout });
  await page.getByRole('button', { name: '載入測試角色', exact: true }).click();
  await page.waitForFunction(() => window.motionDemo.snapshot().errors
    .some((message) => message.includes('動作影片預載失敗')), null, { timeout: phaseTimeout });
  const result = await page.evaluate(() => ({
    ...window.__motionE2ePreloadProbe, snapshot: window.motionDemo.snapshot(),
  }));
  assert.ok(failedFetches > 0, '沒有實際攔截 whole-file 動作影片預載');
  assert.equal(result.sdkInitCalls, 0, '預載失敗消耗了 SDK singleton');
  assert.equal(result.wasmCalls, 0, '預載失敗仍初始化 WASM');
  assert.equal(result.snapshot.ready, false, '預載失敗卻回報 ready');
  assert.equal(result.snapshot.frameCount, 0, '預載失敗仍啟動角色渲染');
  assert.ok(!requests.some(({ path }) => /\.wasm(?:[./]|$)/i.test(path)), '預載失敗仍下載 WASM');
  assert.ok(await page.locator('#error').isVisible(), '預載失敗訊息不可見');
  assert.match(await page.locator('#error').innerText(), /動作影片預載失敗/);
  await page.screenshot({ path: join(artifactDir, 'preload-failure-375.png'), fullPage: true });
  check('failed-video-preload-does-not-initialize-sdk-or-wasm', { failedFetches, ...result });
  await context.close();
  context = undefined;
  page = undefined;
}

await mkdir(artifactDir, { recursive: true });
try {
  assert.ok(username && password, '請設定 MOTION_TEST_USERNAME 及 MOTION_TEST_PASSWORD；腳本沒有內建帳密。');
  const { chromium } = loadPlaywright();
  browser = await chromium.launch({
    executablePath: process.env.MOTION_CHROME_PATH ?? '/usr/bin/google-chrome',
    headless: process.env.MOTION_HEADED !== '1',
    args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'],
  });
  report.browser = { version: browser.version(), executable: process.env.MOTION_CHROME_PATH ?? '/usr/bin/google-chrome' };
  if (!cacheFocusedOnly) {
  phase = 'anonymous-access';
  context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 375, height: 960 },
    serviceWorkers: 'block',
  });
  await protectContext(context);
  page = await context.newPage();
  await watchNetwork(page, 'anonymous-login-recovery');
  const anonymousRequests = [];
  const anonymousResponses = [];
  const anonymousFailedRequests = [];
  report.anonymousRequests = anonymousRequests;
  report.anonymousResponses = anonymousResponses;
  report.anonymousFailedRequests = anonymousFailedRequests;
  page.on('request', (request) => anonymousRequests.push({
    method: request.method(), path: new URL(request.url()).pathname,
  }));
  page.on('response', (response) => anonymousResponses.push({
    path: new URL(response.url()).pathname, status: response.status(),
  }));
  page.on('requestfailed', (request) => anonymousFailedRequests.push({
    method: request.method(), path: new URL(request.url()).pathname,
    error: request.failure()?.errorText,
  }));
  page.on('pageerror', (error) => report.pageErrors.push(error.message));
  await page.addInitScript(() => {
    const probe = window.__motionE2eAccessProbe = {
      documentId: `${Date.now()}-${Math.random()}`, sdkInitCalls: 0, wasmCalls: 0,
    };
    for (const name of ['instantiate', 'instantiateStreaming']) {
      const original = WebAssembly[name];
      if (original) WebAssembly[name] = function (...args) {
        probe.wasmCalls += 1;
        return Reflect.apply(original, this, args);
      };
    }
  });
  await page.goto(demoURL, { waitUntil: 'domcontentloaded', timeout: readyTimeout });
  await page.waitForFunction(() => Boolean(window.motionDemo), null, { timeout: readyTimeout });
  await page.evaluate(() => {
    const sdk = window.OpenVmanAvatar;
    if (!sdk?.init) throw new Error('無法觀察 SDK init 次數：SDK 尚未定義');
    const init = sdk.init;
    // The SDK exports a frozen object; replace its writable global binding
    // rather than attempting to mutate the frozen init property.
    window.OpenVmanAvatar = {
      ...sdk,
      init(...args) {
        window.__motionE2eAccessProbe.sdkInitCalls += 1;
        return Reflect.apply(init, sdk, args);
      },
    };
  });
  await page.waitForFunction(() => window.motionDemo.snapshot().access === 'login-required', null, { timeout: phaseTimeout });
  const loginLink = page.getByRole('link', { name: '登入 Vman', exact: true });
  await loginLink.waitFor({ state: 'visible' });
  assert.equal(new URL(await loginLink.getAttribute('href'), demoURL).pathname, '/admin/login');
  assert.equal(await loginLink.getAttribute('target'), '_blank');
  const recheck = page.getByRole('button', { name: '登入後重新檢查', exact: true });
  await recheck.waitFor({ state: 'visible' });
  const anonymousLoad = page.locator('#load');
  assert.equal(await anonymousLoad.count(), 1, '匿名頁缺少載入控制項');
  assert.ok(!await anonymousLoad.isVisible() || await anonymousLoad.isDisabled(), '匿名使用者仍可載入受保護角色');
  // Leave time for an accidental deferred initialization to become observable.
  await sleep(500);
  const anonymousProbe = await page.evaluate(() => ({
    ...window.__motionE2eAccessProbe, snapshot: window.motionDemo.snapshot(),
  }));
  assert.equal(anonymousProbe.snapshot.ready, false, '匿名頁已初始化受保護角色');
  assert.equal(anonymousProbe.sdkInitCalls, 0, '匿名頁不應呼叫 SDK init');
  assert.equal(anonymousProbe.wasmCalls, 0, '匿名頁不應初始化 WASM');
  assert.ok(!anonymousRequests.some(({ path }) => path.includes('/static/characters/0624/')), '匿名頁請求受保護的 0624 素材');
  assert.ok(!anonymousRequests.some(({ path }) => /\.wasm(?:[./]|$)/i.test(path)), '匿名頁載入 WASM');
  await page.screenshot({ path: join(artifactDir, 'anonymous-login-required-375.png'), fullPage: true });
  check('anonymous-login-required-without-protected-assets-or-wasm', anonymousProbe);

  phase = 'anonymous-login-recheck-same-document';
  const anonymousLogin = await context.request.post(new URL('/api/v1/auth/admin-login', baseURL).href, {
    data: { username, password },
  });
  assert.ok(anonymousLogin.ok(), `匿名 context 登入失敗：HTTP ${anonymousLogin.status()}`);
  await recheck.click();
  await page.waitForFunction(() => window.motionDemo.snapshot().access === 'available', null, { timeout: phaseTimeout });
  const availableProbe = await page.evaluate(() => ({ ...window.__motionE2eAccessProbe }));
  assert.equal(availableProbe.documentId, anonymousProbe.documentId, '登入後重新檢查造成整頁 reload');
  assert.equal(availableProbe.sdkInitCalls, 0, '重新檢查應等待使用者載入角色');
  await page.getByRole('button', { name: '載入測試角色', exact: true }).click();
  await page.evaluate(async (timeout) => {
    await Promise.race([
      window.motionDemo.ready,
      new Promise((_, reject) => setTimeout(() => reject(new Error('登入後 SDK ready timeout')), timeout)),
    ]);
  }, readyTimeout);
  await settled('idle');
  const recovered = await snapshot('anonymous-login-recovered');
  assert.equal(recovered.access, 'available');
  assertSourceBundle(recovered, 'anonymous-login-recovered');
  assert.ok(recovered.frameCount > 0, '匿名登入恢復後沒有真實 SDK 畫面');
  await frame('anonymous-login-recovered');
  const recoveredProbe = await page.evaluate(() => ({ ...window.__motionE2eAccessProbe }));
  assert.equal(recoveredProbe.documentId, anonymousProbe.documentId, '角色載入造成整頁 reload');
  assert.equal(recoveredProbe.sdkInitCalls, 1, '同文件登入恢復必須只初始化 SDK 一次');
  assert.ok(!anonymousResponses.some(({ path, status }) => status === 404 && /character|0624/i.test(path)), '登入恢復仍遇到 Character data HTTP 404');
  assert.deepEqual(report.pageErrors, [], '匿名登入恢復流程出現未捕捉例外');
  await page.screenshot({ path: join(artifactDir, 'anonymous-login-recovered-375.png'), fullPage: true });
  check('anonymous-login-recheck-recovers-once-without-reload-or-character-404', recoveredProbe);
  await context.close();
  context = undefined;
  page = undefined;

  phase = 'authenticated-context';
  context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 960 },
    recordVideo: { dir: join(artifactDir, 'playwright-video'), size: { width: 1440, height: 960 } },
    serviceWorkers: 'block',
  });
  await protectContext(context);
  phase = 'login';
  const login = await context.request.post(new URL('/api/v1/auth/admin-login', baseURL).href, {
    data: { username, password },
  });
  assert.ok(login.ok(), `登入失敗：HTTP ${login.status()}`);
  check('authenticated', { status: login.status() });

  page = await context.newPage();
  await watchNetwork(page, 'authenticated-full');
  video = page.video();
  report.runtimeRequests = runtimeRequests;
  page.on('request', (request) => {
    const url = new URL(request.url());
    runtimeRequests.push({ method: request.method(), path: url.pathname, protocol: url.protocol });
  });
  page.on('pageerror', (error) => report.pageErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') report.consoleErrors.push(message.text());
  });
  page.on('requestfailed', (request) => report.failedRequests.push({
    method: request.method(), path: new URL(request.url()).pathname,
    error: request.failure()?.errorText,
  }));
  page.on('response', (response) => report.requests.push({
    method: response.request().method(), path: new URL(response.url()).pathname, status: response.status(),
  }));
  await page.addInitScript(() => {
    const probe = window.__motionE2eRuntimeProbe = {
      documentId: `${Date.now()}-${Math.random()}`, sdkInitCalls: 0, wasmCalls: 0,
    };
    for (const name of ['instantiate', 'instantiateStreaming']) {
      const original = WebAssembly[name];
      if (original) WebAssembly[name] = function (...args) {
        probe.wasmCalls += 1;
        return Reflect.apply(original, this, args);
      };
    }
    const NativeRecorder = window.MediaRecorder;
    window.__motionE2eRecorders = { created: 0 };
    if (!NativeRecorder) return;
    // Count actual browser recorder construction, independently of demo state.
    window.MediaRecorder = class extends NativeRecorder {
      constructor(...args) {
        super(...args);
        window.__motionE2eRecorders.created += 1;
      }
    };
  });
  phase = 'ready';
  await page.goto(demoURL, { waitUntil: 'domcontentloaded', timeout: readyTimeout });
  await page.waitForFunction(() => Boolean(window.motionDemo?.ready), null, { timeout: readyTimeout });
  await page.evaluate(() => {
    const sdk = window.OpenVmanAvatar;
    if (!sdk?.init) throw new Error('無法觀察 ROOT SDK init 次數');
    const init = sdk.init;
    window.OpenVmanAvatar = {
      ...sdk,
      init(...args) {
        window.__motionE2eRuntimeProbe.sdkInitCalls += 1;
        return Reflect.apply(init, sdk, args);
      },
    };
  });
  await page.getByRole('button', { name: '載入測試角色', exact: true }).click();
  await page.evaluate(async (timeout) => {
    await Promise.race([
      window.motionDemo.ready,
      new Promise((_, reject) => setTimeout(() => reject(new Error('SDK ready timeout')), timeout)),
    ]);
  }, readyTimeout);
  await settled('idle');
  const initial = await snapshot('ready');
  assertSourceBundle(initial, 'ready');
  assert.ok(initial.frameCount > 0, 'SDK 沒有繪出 vendor 影片幀');
  assert.ok(initial.duration > 0, '影片長度無效');
  assert.equal(initial.runtime.sdkInitCalls, 1, '角色首次載入必須只初始化 SDK 一次');
  assert.ok(initial.media?.source.startsWith('blob:'), '快取必須沿用記憶體中的同一份影片 blob');
  assertCacheShape(initial, 'ready');
  runtimeBaseline = {
    runtime: initial.runtime, resources: runtimeRequests.filter(isCharacterResource),
    source: initial.media.source, segments: initial.segments, frameCount: initial.frameCount,
  };
  report.runtimeBaseline = runtimeBaseline;
  for (const name of ALL_STATES) {
    const segment = initial.segments[name];
    assert.ok(segment && Number.isFinite(segment.start) && Number.isFinite(segment.end)
      && segment.start >= 0 && segment.end > segment.start && segment.end <= initial.duration + 0.1,
    `${name}: segment 範圍無效`);
  }
  check('real-sdk-ready', { duration: initial.duration, segments: initial.segments });

  phase = 'responsive';
  for (const width of [320, 375, 414, 768, 1440]) {
    await page.setViewportSize({ width, height: 960 });
    await sleep(250);
    const layout = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
    }));
    assert.ok(layout.documentWidth <= layout.viewport + 1 && layout.bodyWidth <= layout.viewport + 1,
      `${width}: 頁面水平溢出 ${JSON.stringify(layout)}`);
    await frame(`responsive-${width}`);
    await page.screenshot({ path: join(artifactDir, `viewport-${width}.png`), fullPage: true });
    check(`responsive-${width}`, layout);
  }
  check('state-label-is-topmost-at-every-responsive-width');

  phase = 'video-cache-warmup';
  await cachePrepared();
  for (const name of ['thinking', 'speaking', 'idle']) {
    await page.evaluate((state) => window.motionDemo.setState(state), name);
    await settled(name);
    await cachePrepared();
    const warm = await snapshot(`cache-warm-${name}`);
    assertTransition(warm.transitions.filter((entry) => entry.state === name && entry.reason !== 'loop').at(-1), `warm-${name}`);
  }
  const prepared = await snapshot('cache-prepared');
  check('video-cache-prepared-and-bounded', { cache: prepared.videoCache, deviceMemory: prepared.deviceMemory });

  phase = 'prepared-segment-cache-hits';
  const expectAllPreparedHits = prepared.videoCache.maxEntries >= 3;
  const cacheVisits = [];
  for (const name of ['thinking', 'speaking', 'idle']) {
    const before = await snapshot(`cache-revisit-${name}-before`);
    await page.evaluate((state) => window.motionDemo.setState(state), name);
    await settled(name);
    await cachePrepared();
    const after = await snapshot(`cache-revisit-${name}-after`);
    const transition = after.transitions.slice(before.transitions.length)
      .filter((entry) => entry.state === name && entry.reason !== 'loop').at(-1);
    assertTransition(transition, `cache-revisit-${name}`, expectAllPreparedHits);
    if (expectAllPreparedHits) assert.ok(after.videoCache.hits > before.videoCache.hits, `${name}: 命中未更新快取計數`);
    const renderingStart = after.frameCount;
    await monitor(`cache-revisit-${name}-render`, 400, { expectedState: name });
    const rendered = await snapshot(`cache-revisit-${name}-rendered`);
    assert.ok(rendered.frameCount > renderingStart, `${name}: 快取交接後 canvas 沒有持續繪圖`);
    assert.ok(rendered.media.currentTime >= initial.segments[name].start - 0.25
      && rendered.media.currentTime <= initial.segments[name].end + 0.25,
    `${name}: 快取交接改變原 segment 時間軸`);
    cacheVisits.push({ state: name, transition, cache: after.videoCache });
  }
  check(expectAllPreparedHits ? 'prepared-segments-hit-cache-with-continuous-rendering'
    : 'limited-memory-cache-keeps-bounded-segment-rendering', { visits: cacheVisits });

  phase = 'segments-and-loops';
  for (const name of LOOP_STATES) {
    await page.evaluate((state) => window.motionDemo.setState(state), name);
    await settled(name);
    await cachePrepared();
    const before = await snapshot(`${name}-start`);
    await page.waitForFunction(({ state, loops }) => {
      const value = window.motionDemo.snapshot();
      return value.state === state && value.loops > loops;
    }, { state: name, loops: before.loops }, { timeout: phaseTimeout });
    await cachePrepared();
    await frame(`${name}-loop`);
    const after = await snapshot(`${name}-loop`);
    const loopTransition = after.transitions.filter((entry) => entry.state === name && entry.reason === 'loop').at(-1);
    assertTransition(loopTransition, `${name}-loop`, true);
    assert.ok(after.videoCache.hits > before.videoCache.hits, `${name}: 循環沒有使用快取`);
    assert.equal(after.videoCache.misses, before.videoCache.misses, `${name}: 已準備的循環發生快取 miss`);
    assert.ok(after.frameCount > before.frameCount, `${name}: 只有 loop 計數增加，vendor 沒有繼續繪圖`);
    assert.ok(after.media && after.media.readyState >= 2, `${name}: vendor 影片沒有可播放資料`);
    assert.ok(after.media.currentTime >= after.segments[name].start - 0.25
      && after.media.currentTime <= after.segments[name].end + 0.25,
    `${name}: 實際影片時間 ${after.media.currentTime} 沒有落在指定 segment`);
    await page.screenshot({ path: join(artifactDir, `state-${name}.png`) });
    check(`segment-${name}-loops`, { before: before.loops, after: after.loops, transition: loopTransition, cache: after.videoCache });
  }

  phase = 'one-shot-actions';
  for (const state of ONE_SHOT_STATES) await verifyOneShot(state, `state-${state}`);

  phase = 'last-request-wins';
  const rapid = await page.evaluate(async () => {
    const states = ['idle', 'greeting', 'thinking', 'bye', 'speaking', 'idle', 'thinking'];
    return Promise.allSettled(states.map((state) => window.motionDemo.setState(state)))
      .then((results) => results.map((result) => ({ status: result.status,
        ...(result.status === 'rejected' ? { reason: String(result.reason) } : {}) })));
  });
  await settled('thinking');
  await monitor('last-request-wins', 1600, { expectedState: 'thinking' });
  check('rapid-switch-last-request-wins', { requests: rapid });

  phase = 'cycle-and-recording';
  await page.evaluate(() => window.motionDemo.stop());
  await settled('idle');
  const overlappingStarts = await page.evaluate(async () => {
    const before = window.__motionE2eRecorders.created;
    await Promise.all([window.motionDemo.startRecording(), window.motionDemo.startRecording()]);
    return { created: window.__motionE2eRecorders.created - before, recording: window.motionDemo.snapshot().recording };
  });
  assert.equal(overlappingStarts.created, 1, '重疊 startRecording 建立了多個 MediaRecorder');
  assert.equal(overlappingStarts.recording, true, '重疊 startRecording 後錄影未啟動');
  check('overlapping-recording-starts-create-one-recorder', overlappingStarts);
  await sleep(250);
  const recordingHandoff = await page.evaluate(async () => {
    const before = window.__motionE2eRecorders.created;
    const [previousBlob] = await Promise.all([
      window.motionDemo.stopRecording(), window.motionDemo.startRecording(),
    ]);
    return {
      created: window.__motionE2eRecorders.created - before,
      previousBlobSize: previousBlob?.size ?? 0,
      recording: window.motionDemo.snapshot().recording,
    };
  });
  assert.equal(recordingHandoff.created, 1, 'stop/start 交接未恰好建立一個新 MediaRecorder');
  assert.ok(recordingHandoff.previousBlobSize > 0, 'stop/start 交接遺失上一輪錄影 Blob');
  assert.equal(recordingHandoff.recording, true, '舊 stopRecording 關閉了交接後的新錄影');
  check('concurrent-recording-stop-start-keeps-new-recorder-active', recordingHandoff);
  assert.equal((await snapshot('recording-started')).recording, true);
  await startCycle();
  const cycleStates = await monitor('normal-cycle', cycleTimeout, { untilCycleDone: true });
  await settled('idle');
  for (const state of ALL_STATES) assert.ok(cycleStates.includes(state), `runCycle 沒有觀察到 ${state}`);
  const recording = await page.evaluate(async () => {
    const blob = await window.motionDemo.stopRecording();
    if (!blob) return null;
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 16384) binary += String.fromCharCode(...bytes.subarray(i, i + 16384));
    return { size: blob.size, type: blob.type, base64: btoa(binary) };
  });
  assert.ok(recording && recording.size > 1024, 'SDK 畫布／音訊錄影沒有產生有效 Blob');
  assert.match(recording.type, /^video\//, '錄影 Blob 不是影片');
  const recordingFile = recording.type.includes('mp4') ? 'video.browser-capture.mp4' : 'video.browser-capture.webm';
  await writeFile(join(artifactDir, recordingFile), Buffer.from(recording.base64, 'base64'));
  let media;
  try {
    const { stdout } = await runFile('ffprobe', [
      '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height,duration',
      '-of', 'json', join(artifactDir, recordingFile),
    ], { timeout: 15000 });
    media = JSON.parse(stdout);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    report.limitations.push('未安裝 ffprobe：已保存 SDK 錄影，但未檢查影片／音軌結構。');
  }
  if (media) {
    assert.ok(media.streams.some((stream) => stream.codec_type === 'video'), 'SDK 錄影缺少影片軌');
    assert.ok(media.streams.some((stream) => stream.codec_type === 'audio'), 'SDK 錄影缺少 SDK 音訊軌');
  }
  let volume;
  try {
    const { stderr } = await runFile('ffmpeg', [
      '-hide_banner', '-nostats', '-i', join(artifactDir, recordingFile),
      '-map', '0:a:0', '-af', 'volumedetect', '-vn', '-sn', '-dn', '-f', 'null', '-',
    ], { timeout: 30000 });
    const mean = stderr.match(/mean_volume:\s*([-+\d.]+|[-+]?inf)\s*dB/i);
    const maximum = stderr.match(/max_volume:\s*([-+\d.]+|[-+]?inf)\s*dB/i);
    volume = { meanVolumeDb: mean?.[1] ?? null, maxVolumeDb: maximum?.[1] ?? null };
    report.audioVolume = volume;
    assert.ok(mean && maximum, 'ffmpeg 沒有輸出音軌 mean_volume／max_volume');
    assert.ok(Number.isFinite(Number(mean[1])) && Number.isFinite(Number(maximum[1])),
      'SDK 錄影音軌是靜音（mean_volume／max_volume 非有限值）');
    assert.ok(Number(maximum[1]) > -50, `SDK 錄影音量過低：max_volume=${maximum[1]} dB`);
    check('recorded-sdk-audio-is-not-silent', volume);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    report.limitations.push('未安裝 ffmpeg：未確認 SDK 錄影音軌的實際音量。');
  }
  assert.equal((await snapshot('recording-stopped')).recording, false);
  check('normal-cycle-and-recording', { states: cycleStates, recording: { file: recordingFile, size: recording.size, type: recording.type, media, volume } });

  phase = 'stop-cancels-stale-cycle';
  await startCycle();
  await page.waitForFunction(() => window.motionDemo.snapshot().state === 'thinking', null, { timeout: phaseTimeout });
  await sleep(350);
  await page.evaluate(() => window.motionDemo.stop());
  await settled('idle');
  // Wait past the entire original cycle, so a late audio completion cannot pass.
  const stopped = await snapshot('stop-start');
  await monitor('after-stop', Number(process.env.MOTION_STOP_OBSERVATION_MS ?? 24000), { expectedState: 'idle' });
  const afterStop = await snapshot('stop-end');
  assert.ok(afterStop.frameCount > stopped.frameCount, '停止示範後待機畫面不再繪圖');
  assert.ok(afterStop.loops > stopped.loops, '停止示範後待機影片沒有循環');
  await page.screenshot({ path: join(artifactDir, 'after-stop.png') });
  check('stop-cancels-stale-cycle-and-keeps-rendering');

  phase = 'network-and-runtime';
  const finalRuntime = await snapshot('final-runtime');
  assertRuntimeStable(finalRuntime, 'final-runtime');
  check('switches-and-loops-reuse-sdk-wasm-character-data-and-video-blob', {
    sdkInitCalls: finalRuntime.runtime.sdkInitCalls,
    wasmCalls: finalRuntime.runtime.wasmCalls,
    characterResourceRequestsAtReady: runtimeBaseline.resources.length,
    characterResourceRequestsAtEnd: runtimeRequests.filter(isCharacterResource).length,
    cache: finalRuntime.videoCache,
  });
  assert.deepEqual(report.forbiddenWrites, [], 'demo 嘗試發送聊天或修改設定');
  assert.deepEqual(report.pageErrors, [], '瀏覽器發生未捕捉例外');
  check('no-chat-or-settings-writes');
  check('no-uncaught-runtime-errors');
  }
  await focusedCacheScenario('mobile-cache');
  await focusedCacheScenario('standby-decode-fallback', true);
  await failedPreloadScenario();
  phase = 'focused-cache-complete';
  assert.deepEqual(report.forbiddenWrites, [], '局部快取測試嘗試修改聊天或設定');
  assert.deepEqual(report.pageErrors, [], '局部快取測試出現未捕捉例外');
  report.limitations.push('375／deviceMemory=2／觸控是 Chrome 模擬；尚未以實體手機驗證。');
  report.passed = true;
} catch (error) {
  report.failure = { phase, message: error.message, stack: error.stack };
  if (page && !page.isClosed()) {
    try { await page.screenshot({ path: join(artifactDir, 'failure.png'), fullPage: true }); } catch { /* Preserve original error. */ }
    try { report.failure.snapshot = await page.evaluate(() => window.motionDemo?.snapshot()); } catch { /* SDK may not exist. */ }
  }
  process.exitCode = 1;
} finally {
  try { await context?.close(); } catch (error) { report.closeError = error.message; process.exitCode = 1; report.passed = false; }
  try { if (video) report.playwrightVideo = await video.path(); } catch { /* Browser did not reach video creation. */ }
  try { await browser?.close(); } catch { /* Context video is already finalized. */ }
  report.finishedAt = new Date().toISOString();
  await writeFile(join(artifactDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify({ passed: report.passed, phase, artifactDir,
    report: join(artifactDir, 'report.json'), checks: report.checks.length,
    ...(report.failure ? { failure: report.failure.message } : {}),
  }, null, 2));
}
