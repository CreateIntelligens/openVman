#!/usr/bin/env node
/** Real SDK/WASM handoff recording using the current production motion session source.
 * Required: MOTION_TEST_USERNAME / MOTION_TEST_PASSWORD.
 * Run from repo root: node frontend/app/scripts/e2e/avatar-motion-handoff.mjs
 * MOTION_ARTIFACT_DIR selects the evidence directory. Does not replace formal Vue chat E2E.
 */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { delimiter, dirname, join, resolve } from 'node:path';

const require = createRequire(import.meta.url);
function playwright() {
  try { return require('playwright-core'); } catch { /* agent-browser installation fallback */ }
  for (const entry of [process.env.MOTION_PLAYWRIGHT_PACKAGE,
    join(dirname(process.execPath), '..', 'lib/node_modules/agent-browser/package.json'),
    ...(process.env.PATH ?? '').split(delimiter).map((path) => join(path, '../lib/node_modules/agent-browser/package.json')),
    '/usr/local/lib/node_modules/agent-browser/package.json'].filter(Boolean)) {
    try { return createRequire(resolve(entry))('playwright-core'); } catch { /* next */ }
  }
  throw new Error('playwright-core unavailable; set MOTION_PLAYWRIGHT_PACKAGE');
}

const { build } = require('../../node_modules/esbuild');
const { outputFiles } = await build({ entryPoints: [resolve('frontend/app/src/composables/avatarMotionSession.ts')], bundle: true, write: false, format: 'iife', globalName: 'MotionSessionProbe' });
const base = process.env.BASE_URL ?? 'https://10.9.0.32:8787';
const output = resolve(process.env.MOTION_ARTIFACT_DIR ?? '/tmp/openvman-motion-20261022/handoff-before');
await mkdir(output, { recursive: true });
const { chromium } = playwright();
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'], headless: true });
let context;
try {
  context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 960 } });
  const login = await context.request.post(base + '/api/v1/auth/admin-login', { data: { username: process.env.MOTION_TEST_USERNAME, password: process.env.MOTION_TEST_PASSWORD } });
  assert.ok(login.ok());
  const page = await context.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.route('**/experiments/avatar-motion/', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><style>body{margin:0;background:#161a20;color:white}#stage{position:relative;height:95dvh;width:100%}#avatar{height:100%;width:100%}#avatar-motion-held{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;z-index:2;opacity:0;pointer-events:none}</style><div id="stage"><div id="avatar"></div><canvas id="avatar-motion-held"></canvas></div><script src="/static/sdk/openvman-avatar-sdk.js"></script>` }));
  await page.goto(base + '/experiments/avatar-motion/');
  await page.waitForFunction(() => window.OpenVmanAvatar);
  await page.addScriptTag({ content: outputFiles[0].text });
  const result = await page.evaluate(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    // SDK loads the same full JSON first; session applyData does not replace it.
    const avatar = await OpenVmanAvatar.init({ characterId: 'hciot-v1', assetsBaseUrl: '/static/characters/hciot-motion/motions', container: document.getElementById('avatar'), zIndex: 0 });
    const session = new MotionSessionProbe.AvatarMotionSession({ baseUrl: '/static/characters/hciot-motion/motions/hciot-v1', signal: new AbortController().signal, applyData() {}, onChange() {}, onUpdate() {} });
    await session.start();
    const sample = await fetch('/experiments/avatar-motion/sample.wav').then(r => r.arrayBuffer());
    const canvas = document.getElementById('canvas_video'), held = document.getElementById('avatar-motion-held');
    const composed = document.createElement('canvas'); composed.width = 540; composed.height = 960;
    const ctx = composed.getContext('2d'), stream = composed.captureStream(25), chunks = [], frames = [];
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8', videoBitsPerSecond: 1800000 });
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    let run = true, previous, lastAt = 0;
    const tick = now => {
      if (!run) return;
      if (now - lastAt >= 38) {
        lastAt = now; ctx.fillStyle = '#161a20'; ctx.fillRect(0, 0, 540, 960);
        ctx.drawImage(canvas, 0, 0, 540, 960);
        ctx.globalAlpha = Number(held.style.opacity); ctx.drawImage(held, 0, 0, 540, 960); ctx.globalAlpha = 1;
        const pixels = ctx.getImageData(0, 0, 540, 960).data;
        let difference = 0, luma = 0;
        for (let i = 0; i < pixels.length; i += 64) { luma += pixels[i]; if (previous) difference += Math.abs(pixels[i] - previous[i]); }
        frames.push({ at: now, state: session.snapshot().state, transitioning: session.snapshot().transitioning, opacity: Number(held.style.opacity), time: characterVideo.currentTime, difference: difference / (pixels.length / 64), luma: luma / (pixels.length / 64) });
        previous = pixels;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick); recorder.start(200);
    for (const duration of [1200, 3500, 6500]) {
      await session.setState('thinking'); await sleep(duration);
      await session.setState('speaking'); await avatar.playAudio(sample.slice(0)); await sleep(400);
      await session.setState('idle'); await sleep(300);
    }
    const blob = await new Promise(resolve => { recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType })); recorder.stop(); });
    run = false; stream.getTracks().forEach(t => t.stop());
    let binary = ''; const bytes = new Uint8Array(await blob.arrayBuffer());
    for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
    const snapshot = session.snapshot(); session.dispose(); avatar.destroy();
    return { frames, snapshot, video: btoa(binary) };
  });
  await writeFile(join(output, 'proof.webm'), Buffer.from(result.video, 'base64')); delete result.video;
  result.pageErrors = errors;
  await writeFile(join(output, 'report.json'), JSON.stringify(result, null, 2));
  assert.deepEqual(errors, []); assert.deepEqual(result.snapshot.errors, []);
  console.log(JSON.stringify({ output, transitions: result.snapshot.transitions, frames: result.frames.length }));
} finally { await context?.close(); await browser.close(); }
