#!/usr/bin/env node
/** Real single-WASM codec pilot. No production playback/source files are changed.
 * Required: MOTION_TEST_USERNAME / MOTION_TEST_PASSWORD.
 * Run: node frontend/app/scripts/e2e/avatar-motion-formats.mjs
 * MOTION_FORMAT_VIEWPORTS=desktop,mobile; MOTION_FORMAT_MODES=all-webm,all-mp4,mixed-state.
 * MP4 must be prepared and its 800 frame markers independently verified first.
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
const base = process.env.BASE_URL ?? 'https://localhost:8787';
const output = resolve(process.env.MOTION_ARTIFACT_DIR ?? '/tmp/openvman-motion-20261022/formats');
const modes = (process.env.MOTION_FORMAT_MODES ?? 'all-webm,all-mp4,mixed-state').split(',');
const viewports = (process.env.MOTION_FORMAT_VIEWPORTS ?? 'desktop,mobile').split(',');
const reportPrefix = process.env.MOTION_FORMAT_REPORT_PREFIX ?? 'report';
const viewportSizes = { desktop: { width: 1440, height: 960 }, mobile: { width: 375, height: 900 } };
const report = { startedAt: new Date().toISOString(), cases: [], passed: false,
  method: {
    cache: 'Independent pilot: four fixed-source video elements; mixed has two WebM and two MP4. Same controller, schedule and 80ms held-frame fade in every case. Not the production MotionVideoCache.',
    preload: 'Both complete encoded files and matching JSON are fetched before SDK initialization in every case; only one SDK/WASM instance per case.',
    warmupMs: 2000, sourceFps: 25, longStallMs: 200,
    measurement: 'No recording during measured phases. requestVideoFrameCallback mediaTime and marker-deduplicated real SDK canvas draws; steady and transition periods separated.',
    recording: 'A separate post-measurement canvas+held-overlay recording repeats the transitions in the same SDK document; its load is excluded from performance statistics.',
    limitations: ['Headless desktop Chromium on this host, not physical mobile hardware.', 'One sequence per mode/viewport; no confidence interval or order randomization.',
      'VideoPlaybackQuality totals include standby decoding/seeking; RVFC skipped-frame estimates are reported separately.', 'Mixed-source pilot cache is not a production integration.'],
  },
};
if (modes.every((mode) => mode === 'single-lipsync')) {
  Object.assign(report.method, {
    cache: 'Native SDK neutral 8-second/200-frame WebM with exactly one video decoder, native loop, no action controller or standby pool.',
    preload: 'One WebM and matching 200-row JSON checked before SDK initialization; one SDK/WASM instance per case.',
    recording: 'Post-measurement 8-second canvas and real SDK audio recording; encoding excluded from measured statistics.',
    audio: 'One repeated-speech WAV scheduled for 18 seconds; source start, realtime analyser RMS and actual mouth-patch draws recorded.',
  });
}
await mkdir(output, { recursive: true });
assert.ok(process.env.MOTION_TEST_USERNAME && process.env.MOTION_TEST_PASSWORD, 'Set MOTION_TEST_USERNAME and MOTION_TEST_PASSWORD');

const html = `<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>HCIOT codec pilot</title>
<style>body{margin:0;background:#17191f;color:#f4f4f4;font:1rem system-ui}main{width:94%;margin:1rem auto;max-width:76rem}h1{font-size:1.3rem}#stage{position:relative;height:75dvh;width:100%;background:#22252d}#avatar{width:100%;height:100%}#held{position:absolute;inset:0;z-index:2;width:100%;height:100%;object-fit:contain;opacity:0;pointer-events:none}#label{position:absolute;top:.5rem;left:.5rem;z-index:3;background:#17191fcc;padding:.5rem}p{font-size:.8rem}</style>
<main><h1>HCIOT · WebM / MP4 格式對照</h1><p id="info">獨立固定來源四 decoder pilot；保持單一真 SDK / WASM</p><div id="stage"><div id="avatar"></div><canvas id="held"></canvas><div id="label">準備中</div></div></main>
<script src="/static/sdk/openvman-avatar-sdk.js"></script></html>`;

async function browserCase(page, mode) {
  return page.evaluate(async ({ mode }) => {
    const single = mode === 'single-lipsync';
    const { MotionSegmentPlayer, seekVideo } = await import('/experiments/avatar-motion/motion-controller.js');
    const asset = single ? '/static/characters/hciot-motion' : '/static/characters/hciot-motion/motions/hciot-v1';
    const segments = single ? { idle: { start: 0, end: 8 }, speaking: { start: 0, end: 8 } }
      : { idle: { start: 0, end: 8 }, thinking: { start: 8, end: 16 }, speaking: { start: 0, end: 8 },
      greeting: { start: 16, end: 24, loop: false, next: 'idle' }, bye: { start: 24, end: 32, loop: false, next: 'idle' } };
    const stateKey = (state) => state === 'speaking' ? 'idle' : state;
    const formatOf = (state) => mode === 'all-webm' ? 'webm' : mode === 'all-mp4' ? 'mp4'
      : ['idle', 'speaking'].includes(state) ? 'webm' : 'mp4';
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const fail = () => new DOMException('cancelled', 'AbortError');
    const fetchOk = async (url) => { const response = await fetch(url); if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`); return response; };
    const [manifest, dataBytes, webm, mp4, sample] = await Promise.all([
      single ? Promise.resolve({ id: 'neutral-hciot-motion', fps: 25, frameCount: 200, width: 1080, height: 1920 }) : fetchOk(`${asset}/manifest.json`).then((r) => r.json()),
      fetchOk(`${asset}/combined_data.json.gz`).then((r) => r.arrayBuffer()),
      fetchOk(`${asset}/01.webm`).then((r) => r.blob()), single ? Promise.resolve(null) : fetchOk(`${asset}/01.mp4`).then((r) => r.blob()),
      fetchOk('/experiments/avatar-motion/sample.wav').then((r) => r.arrayBuffer()),
    ]);
    const expectedFrames = single ? 200 : 800;
    if (manifest.fps !== 25 || manifest.frameCount !== expectedFrames || manifest.width !== 1080 || manifest.height !== 1920) throw new Error('Unexpected motion manifest');
    const raw = new Uint8Array(dataBytes);
    const dataText = raw[0] === 0x1f && raw[1] === 0x8b
      ? await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))).text()
      : new TextDecoder().decode(raw);
    if (JSON.parse(dataText).json_data?.length !== expectedFrames) throw new Error('JSON timeline frame count mismatch');
    const dataHash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', dataBytes))].map((v) => v.toString(16).padStart(2, '0')).join('');
    const urls = { webm: URL.createObjectURL(webm), mp4: mp4 ? URL.createObjectURL(mp4) : null };
    let avatar, player, pool, measuring = false, phase = 'warmup', epoch = 0, frameCount = 0, lastSource;
    let frozen = false, disposed = false, originalDraw, context, continuousAudio = false, audioTask;
    let speechBytes = sample, audioTap = null, analyser = null, meterTimer = null, mouthPatchDraws = 0;
    const audioEvidence = { starts: [], rms: [], mouthPatchDraws: 0 };
    const nativeAudioStart = AudioBufferSourceNode.prototype.start;
    if (single) {
      // Build one continuous input so repeated playAudio calls do not reset the runtime.
      const decoder = new AudioContext();
      const decoded = await decoder.decodeAudioData(sample.slice(0));
      const source = decoded.getChannelData(0), rate = decoded.sampleRate, count = rate * 18;
      speechBytes = new ArrayBuffer(44 + count * 2);
      const header = new DataView(speechBytes);
      const chars = (offset, value) => [...value].forEach((char, index) => header.setUint8(offset + index, char.charCodeAt(0)));
      chars(0, 'RIFF'); header.setUint32(4, 36 + count * 2, true); chars(8, 'WAVE'); chars(12, 'fmt ');
      header.setUint32(16, 16, true); header.setUint16(20, 1, true); header.setUint16(22, 1, true);
      header.setUint32(24, rate, true); header.setUint32(28, rate * 2, true); header.setUint16(32, 2, true); header.setUint16(34, 16, true);
      chars(36, 'data'); header.setUint32(40, count * 2, true);
      for (let i = 0; i < count; i++) header.setInt16(44 + i * 2, Math.round(Math.max(-1, Math.min(1, source[i % source.length])) * 32767), true);
      await decoder.close();
      AudioBufferSourceNode.prototype.start = function (...args) {
        if (!audioTap) {
          audioTap = this.context.createMediaStreamDestination();
          analyser = this.context.createAnalyser(); analyser.fftSize = 256;
          const silence = this.context.createGain(); silence.gain.value = 0;
          analyser.connect(silence); silence.connect(this.context.destination);
          const samples = new Float32Array(analyser.fftSize);
          meterTimer = setInterval(() => {
            if (!measuring) return;
            analyser.getFloatTimeDomainData(samples);
            audioEvidence.rms.push(Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length));
          }, 100);
        }
        this.connect(audioTap); this.connect(analyser);
        if (measuring) audioEvidence.starts.push({ contextState: this.context.state, duration: this.buffer?.duration, at: performance.now() });
        return Reflect.apply(nativeAudioStart, this, args);
      };
    }
    const errors = [], rvfc = [], canvasFrames = [], activations = [], seekLog = [];
    const markerMismatches = [], videoEntries = [], phases = [];
    const held = document.getElementById('held'), label = document.getElementById('label');
    const markerCanvas = document.createElement('canvas'); markerCanvas.width = markerCanvas.height = 2;
    const markerContext = markerCanvas.getContext('2d', { willReadFrequently: true });
    const nativeRead = CanvasRenderingContext2D.prototype.getImageData;
    let previousCanvasKey;
    function markerMean(pixels) { let sum = 0; for (let i = 0; i < pixels.length; i += 4) sum += pixels[i] + pixels[i + 1] + pixels[i + 2]; return sum / 12; }
    function markerValue(pixels) { return Math.round(markerMean(pixels) / 40); }
    const metadata = () => ({ at: performance.now(), phase, epoch, state: player?.state ?? 'idle', transition: Boolean(player?.transitioning) });
    function observeVideo(entry) {
      const callback = (now, frame) => {
        if (disposed) return;
        if (measuring && entry.video === window.characterVideo) {
          const callbackAt = performance.now(), currentTimeBeforeRead = entry.video.currentTime;
          markerContext.drawImage(entry.video, entry.video.videoWidth - 2, 0, 2, 2, 0, 0, 2, 2);
          const sampleMean = markerMean(markerContext.getImageData(0, 0, 2, 2).data), code = Math.round(sampleMean / 40);
          const index = Math.round(frame.mediaTime * 25);
          const sample = { ...metadata(), at: now, format: entry.format, video: entry.id, mediaTime: frame.mediaTime,
            frame: index, presentedFrames: frame.presentedFrames, marker: code, markerExpected: index % 7,
            callbackAt, currentTimeBeforeRead, currentTimeAfterRead: entry.video.currentTime,
            expectedDisplayTime: frame.expectedDisplayTime, presentationTime: frame.presentationTime,
            processingDuration: frame.processingDuration, markerSampleMean: sampleMean };
          rvfc.push(sample);
          if (code !== index % 7) markerMismatches.push(sample);
        }
        entry.callback = entry.video.requestVideoFrameCallback(callback);
      };
      entry.callback = entry.video.requestVideoFrameCallback(callback);
    }
    async function loadVideo(video, source) {
      video.pause(); video.muted = true; video.playsInline = true; video.loop = false; video.preload = 'auto';
      await new Promise((resolve, reject) => {
        const finish = (error) => { clearTimeout(timer); video.removeEventListener('loadeddata', loaded); video.removeEventListener('error', failed); error ? reject(error) : resolve(); };
        const loaded = () => finish(), failed = () => finish(new Error('decoder load failed'));
        const timer = setTimeout(() => finish(new Error('decoder load timeout')), 20000);
        video.addEventListener('loadeddata', loaded); video.addEventListener('error', failed); video.src = source; video.load();
      });
    }
    function freeze() {
      if (!frozen) { const canvas = document.getElementById('canvas_video'); held.width = canvas.width; held.height = canvas.height; held.getContext('2d').drawImage(canvas, 0, 0); }
      frozen = true; held.style.opacity = '1';
    }
    async function renderedAndFade(signal, selected) {
      const first = frameCount, started = performance.now();
      await new Promise((resolve, reject) => {
        const tick = () => {
          if (signal.aborted) return reject(fail());
          if (frameCount > first && lastSource === selected) return resolve();
          if (performance.now() - started > 5000) return reject(new Error('real WASM canvas frame timeout'));
          requestAnimationFrame(tick);
        }; tick();
      });
      const fadeStart = performance.now();
      await new Promise((resolve, reject) => {
        const tick = () => {
          if (signal.aborted) return reject(fail());
          const amount = Math.min(1, (performance.now() - fadeStart) / 80); held.style.opacity = String(1 - amount);
          if (amount === 1) return resolve(); requestAnimationFrame(tick);
        }; requestAnimationFrame(tick);
      });
      frozen = false;
    }
    const abortable = (promise, signal) => new Promise((resolve, reject) => {
      const abort = () => reject(fail()); signal.addEventListener('abort', abort, { once: true });
      promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort)); if (signal.aborted) abort();
    });
    // Independent pilot cache: each decoder keeps its original Blob source for its entire lifetime.
    class PilotPool {
      constructor(active) { this.active = active; this.hits = 0; this.misses = 0; }
      prepare(entry, state) {
        if (entry.video === this.active) throw new Error('attempted to seek the active decoder');
        entry.abort?.abort(); const abort = entry.abort = new AbortController(); entry.state = stateKey(state); entry.ready = false;
        entry.video.pause(); seekLog.push({ ...metadata(), video: entry.id, format: entry.format, state: entry.state });
        const pending = seekVideo(entry.video, segments[state].start, abort.signal).then(() => { if (!abort.signal.aborted) entry.ready = true; })
          .finally(() => { if (entry.pending === pending) entry.pending = null; });
        pending.catch(() => {}); entry.pending = pending; return pending;
      }
      async acquire(state, signal) {
        if (signal.aborted) throw fail();
        const available = videoEntries.filter((entry) => entry.video !== this.active && entry.format === formatOf(state));
        let entry = available.find((item) => item.state === stateKey(state));
        const hit = Boolean(entry?.ready); hit ? this.hits++ : this.misses++;
        entry ??= available.find((item) => !item.pending) ?? available[0];
        if (!entry) throw new Error('no matching-format standby decoder');
        if (!hit && (entry.state !== stateKey(state) || !entry.pending)) this.prepare(entry, state);
        if (entry.pending) await abortable(entry.pending, signal);
        if (signal.aborted) throw fail();
        if (!entry.ready || entry.state !== stateKey(state)) return this.acquire(state, signal);
        return { video: entry.video, cacheHit: hit };
      }
      activate(selected, state) {
        const entry = videoEntries.find((item) => item.video === selected), previous = videoEntries.find((item) => item.video === this.active);
        if (!entry.ready || entry.state !== stateKey(state)) throw new Error('stale pilot cache entry');
        this.active = selected; window.characterVideo = selected; epoch++;
        activations.push({ ...metadata(), state, format: entry.format, video: entry.id });
        const refill = previous.format === formatOf(state) ? state : previous.format === formatOf('idle') ? 'idle' : 'thinking';
        void this.prepare(previous, refill);
      }
    }
    try {
      avatar = await window.OpenVmanAvatar.init({ ...(single ? { characterId: 'hciot-motion' }
        : { characterId: 'hciot-v1', assetsBaseUrl: '/static/characters/hciot-motion/motions' }), container: document.getElementById('avatar'), zIndex: 0 });
      const canvas = document.getElementById('canvas_video'); context = canvas.getContext('2d'); originalDraw = context.drawImage;
      context.drawImage = function (source, ...args) {
        const result = Reflect.apply(originalDraw, this, [source, ...args]);
        if (measuring && args.length === 8 && args[2] === 180 && args[3] === 180) mouthPatchDraws++;
        if (source === window.characterVideo) {
          frameCount++; lastSource = source;
          if (measuring) {
            const entry = videoEntries.find((item) => item.video === source);
            if (entry) {
              const code = markerValue(nativeRead.call(context, canvas.width - 2, 0, 2, 2).data), approximate = Math.floor(source.currentTime * 25);
              let frame = approximate; for (let offset = -3; offset <= 3; offset++) if (approximate + offset >= 0 && (approximate + offset) % 7 === code) { frame = approximate + offset; break; }
              const key = `${epoch}:${entry.id}:${frame}`;
              if (key !== previousCanvasKey) { previousCanvasKey = key; canvasFrames.push({ ...metadata(), frame, format: entry.format, video: entry.id }); }
            }
          }
        }
        return result;
      };
      const formats = single ? ['webm'] : mode === 'mixed-state' ? ['webm', 'webm', 'mp4', 'mp4'] : Array(4).fill(mode === 'all-webm' ? 'webm' : 'mp4');
      for (let index = 0; index < formats.length; index++) {
        const video = index === 0 ? window.characterVideo : document.createElement('video');
        if (index) { video.hidden = true; document.body.appendChild(video); }
        await loadVideo(video, urls[formats[index]]);
        if (video.videoWidth !== 1080 || video.videoHeight !== 1920 || video.duration < (single ? 7.99 : 31.99)) throw new Error('wrong decoded geometry/timeline');
        const entry = { id: `v${index}`, format: formats[index], video, state: null, pending: null, ready: false };
        videoEntries.push(entry); observeVideo(entry);
      }
      if (!single) {
      pool = new PilotPool(videoEntries[0].video);
      for (let index = 1; index < 4; index++) await pool.prepare(videoEntries[index], mode === 'mixed-state' ? ['idle', 'idle', 'thinking', 'greeting'][index] : ['idle', 'idle', 'thinking', 'greeting'][index]);
      player = new MotionSegmentPlayer(pool.active, segments, {
        beforeSeek: freeze, acquireVideo: (state, signal) => pool.acquire(state, signal), activateVideo: (video, state) => pool.activate(video, state),
        afterSeek: (_state, signal, video) => renderedAndFade(signal, video), onChange: (state) => { label.textContent = `${mode} · ${state}`; },
        onError: (error) => errors.push(String(error)),
      });
      await player.setState('idle');
      } else {
        // Native SDK neutral bundle, one decoder, native loop: no pool or action controller.
        window.characterVideo.loop = true; await window.characterVideo.play();
        player = { state: 'speaking', transitioning: false, transitions: [], errors: [], loops: null,
          dispose() { window.characterVideo.pause(); } };
        label.textContent = 'single-lipsync · one WebM decoder · native SDK';
      }
      await sleep(2000);
      const quality = () => videoEntries.map(({ id, format, video }) => ({ id, format, ...video.getVideoPlaybackQuality().toJSON?.(),
        totalVideoFrames: video.getVideoPlaybackQuality().totalVideoFrames, droppedVideoFrames: video.getVideoPlaybackQuality().droppedVideoFrames }));
      const qualityBefore = quality(), runtimeBaseline = { ...window.__formatRuntime };
      const transitionStart = player.transitions.length, activationStart = activations.length;
      measuring = true;
      async function phaseRun(name, state, ms) {
        phase = name; const start = performance.now(); if (state) await player.setState(state);
        if (state === 'speaking') void avatar.playAudio(sample.slice(0)).catch((error) => errors.push(String(error)));
        await sleep(ms); if (state === 'speaking') avatar.interrupt();
        phases.push({ name, start, end: performance.now() });
      }
      if (single) {
        phase = 'single-continuous-lipsync'; continuousAudio = true;
        const start = performance.now();
        await avatar.playAudio(speechBytes.slice(0)); continuousAudio = false;
        phases.push({ name: phase, start, end: performance.now() });
      } else {
      await phaseRun('idle-steady-and-loop', null, 8500);
      await phaseRun('thinking-steady-and-loop', 'thinking', 8500);
      await phaseRun('speaking-steady', 'speaking', 3000);
      await phaseRun('greeting-switch', 'greeting', 1400);
      await phaseRun('bye-switch', 'bye', 1400);
      phase = 'rapid-switches'; const rapid = [];
      for (const state of ['idle', 'thinking', 'greeting', 'speaking', 'bye', 'idle', 'thinking', 'speaking', 'greeting', 'bye', 'thinking', 'idle']) {
        rapid.push(player.setState(state)); await sleep(60);
      }
      const rapidResults = await Promise.all(rapid); await phaseRun('idle-recovered', 'idle', 2000);
      phases.push({ name: 'rapid-results', cancelled: rapidResults.filter((result) => !result).length });
      }
      measuring = false;
      audioEvidence.mouthPatchDraws = mouthPatchDraws;
      const qualityAfter = quality();
      const measured = { mode, manifest, jsonRows: expectedFrames, jsonSha256: dataHash, encodedBytes: { webm: webm.size, mp4: mp4?.size ?? null },
        userAgent: navigator.userAgent, videoCodecs: { webm: 'VP9', mp4: 'H264 High yuv420p' }, geometry: { width: 1080, height: 1920, fps: 25, frames: expectedFrames },
        decoderLayout: videoEntries.map(({ id, format, video }) => ({ id, format, blobSource: video.src === urls[format] })),
        runtimeBaseline, runtimeAfter: { ...window.__formatRuntime }, qualityBefore, qualityAfter,
        transitions: player.transitions.slice(transitionStart), activations: activations.slice(activationStart), phases,
        rvfc, canvasFrames, markerMismatches, errors: [...errors, ...player.errors], loops: player.loops,
        cache: pool ? { hits: pool.hits, misses: pool.misses } : null,
        ...(single ? { audioEvidence, domVideoCount: document.querySelectorAll('video').length } : {}),
        cancelledRapidRequests: phases.find((entry) => entry.name === 'rapid-results')?.cancelled ?? 0 };
      document.getElementById('info').textContent = `${mode} · measured · ${rvfc.length} decoder frames · ${markerMismatches.length} marker mismatches`;
      window.formatPilot = { measured, async record() {
        const composed = document.createElement('canvas'); composed.width = 720; composed.height = 1280;
        const ctx = composed.getContext('2d'), stream = composed.captureStream(25), mimeType = single ? 'video/webm;codecs=vp8,opus' : 'video/webm;codecs=vp8';
        if (single && audioTap) audioTap.stream.getAudioTracks().forEach((track) => stream.addTrack(track));
        const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 1800000 }), chunks = [];
        recorder.addEventListener('dataavailable', (event) => { if (event.data.size) chunks.push(event.data); });
        let frame, painting = true;
        const paint = () => { if (!painting) return; ctx.fillStyle = '#22252d'; ctx.fillRect(0, 0, 720, 1280); ctx.drawImage(canvas, 0, 0, 720, 1280);
          const opacity = Number(held.style.opacity); if (opacity > 0) { ctx.globalAlpha = opacity; ctx.drawImage(held, 0, 0, 720, 1280); ctx.globalAlpha = 1; }
          ctx.fillStyle = '#17191f'; ctx.fillRect(0, 0, 720, 60); ctx.fillStyle = 'white'; ctx.font = '1.5rem system-ui'; ctx.fillText(`${mode} · ${player.state}`, 20, 38); frame = requestAnimationFrame(paint); };
        paint(); recorder.start(250);
        if (single) { audioTask = avatar.playAudio(speechBytes.slice(0));
          await sleep(8000); avatar.interrupt(); await audioTask;
        } else for (const state of ['idle', 'thinking', 'speaking', 'greeting', 'bye', 'idle']) { await player.setState(state); await sleep(1300); }
        const blob = await new Promise((resolve) => { recorder.addEventListener('stop', () => resolve(new Blob(chunks, { type: recorder.mimeType })), { once: true }); recorder.stop(); });
        painting = false; cancelAnimationFrame(frame); stream.getTracks().forEach((track) => track.stop());
        let binary = ''; const bytes = new Uint8Array(await blob.arrayBuffer()); for (let start = 0; start < bytes.length; start += 32768) binary += String.fromCharCode(...bytes.subarray(start, start + 32768));
        return btoa(binary);
      }, cleanup() { disposed = true; player.dispose(); for (const entry of videoEntries) { entry.abort?.abort(); entry.video.cancelVideoFrameCallback(entry.callback); entry.video.pause(); }
        clearInterval(meterTimer); if (single) AudioBufferSourceNode.prototype.start = nativeAudioStart;
        continuousAudio = false; avatar.interrupt(); context.drawImage = originalDraw; avatar.destroy(); for (const entry of videoEntries) entry.video.remove(); Object.values(urls).filter(Boolean).forEach(URL.revokeObjectURL); } };
      return measured;
    } catch (error) {
      clearInterval(meterTimer); if (single) AudioBufferSourceNode.prototype.start = nativeAudioStart;
      disposed = true; player?.dispose(); if (context && originalDraw) context.drawImage = originalDraw;
      continuousAudio = false; avatar?.destroy(); for (const entry of videoEntries) { entry.abort?.abort(); entry.video.pause(); entry.video.remove(); } Object.values(urls).filter(Boolean).forEach(URL.revokeObjectURL);
      throw error;
    }
  }, { mode });
}

function summarizeSamples(samples) {
  const steady = [], transition = [], mediaSkips = [];
  for (let i = 1; i < samples.length; i++) {
    const before = samples[i - 1], after = samples[i], gap = after.at - before.at;
    if (before.epoch === after.epoch && !before.transition && !after.transition && before.phase === after.phase) {
      steady.push(gap);
      if (typeof after.mediaTime === 'number') mediaSkips.push(Math.max(0, Math.round((after.mediaTime - before.mediaTime) * 25) - 1));
    } else transition.push(gap);
  }
  const stats = (values) => { const ordered = [...values].sort((a, b) => a - b); return { n: values.length,
    medianMs: ordered[Math.floor(ordered.length * .5)] ?? null, p95Ms: ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * .95))] ?? null,
    maxMs: ordered.at(-1) ?? null, stallsOver200ms: values.filter((value) => value > 200).length }; };
  return { steady: stats(steady), transitions: stats(transition), rvfcEstimatedSkippedSourceFrames: mediaSkips.reduce((a, b) => a + b, 0) };
}
function summarize(value) {
  const quality = value.qualityAfter.map((after, i) => ({ id: after.id, format: after.format,
    total: after.totalVideoFrames - value.qualityBefore[i].totalVideoFrames,
    dropped: after.droppedVideoFrames - value.qualityBefore[i].droppedVideoFrames }));
  const ms = value.transitions.map((entry) => entry.ms).sort((a, b) => a - b);
  return { videoQuality: quality, totalFrames: quality.reduce((n, item) => n + item.total, 0), droppedFrames: quality.reduce((n, item) => n + item.dropped, 0),
    rvfc: summarizeSamples(value.rvfc), canvas: summarizeSamples(value.canvasFrames),
    handoff: { n: ms.length, medianMs: ms[Math.floor(ms.length / 2)] ?? null, p95Ms: ms[Math.min(ms.length - 1, Math.floor(ms.length * .95))] ?? null, maxMs: ms.at(-1) ?? null },
    mixedCodecSwitches: value.activations.slice(1).filter((entry, i) => entry.format !== value.activations[i].format).length,
    actualFormats: [...new Set(value.activations.map((entry) => entry.format))], markerMismatches: value.markerMismatches.length,
    cancelledRapidRequests: value.cancelledRapidRequests, errors: value.errors };
}

let browser;
try {
  const { chromium } = playwright();
  browser = await chromium.launch({ executablePath: process.env.MOTION_CHROME_PATH ?? '/usr/bin/google-chrome', headless: true,
    args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'] });
  report.browser = { version: browser.version(), executable: process.env.MOTION_CHROME_PATH ?? '/usr/bin/google-chrome' };
  for (const viewport of viewports) for (const mode of modes) {
    assert.ok(viewportSizes[viewport] && ['all-webm', 'all-mp4', 'mixed-state', 'single-lipsync'].includes(mode), 'Unknown viewport/mode');
    const name = `${viewport}-${mode}`, result = { name, viewport: viewportSizes[viewport], passed: false };
    const context = await browser.newContext({ viewport: viewportSizes[viewport], ignoreHTTPSErrors: true, serviceWorkers: 'block',
      ...(viewport === 'mobile' ? { isMobile: true, hasTouch: true, deviceScaleFactor: 1 } : {}) });
    let page;
    try {
      console.log(`[START] ${name}`);
      const login = await context.request.post(`${base}/api/v1/auth/admin-login`, { data: { username: process.env.MOTION_TEST_USERNAME, password: process.env.MOTION_TEST_PASSWORD } });
      assert.ok(login.ok(), `Login HTTP ${login.status()}`);
      page = await context.newPage(); const pageErrors = [], forbiddenWrites = [];
      page.on('pageerror', (error) => pageErrors.push(error.message));
      await page.route('**/*', async (route) => {
        const request = route.request(), path = new URL(request.url()).pathname;
        if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { forbiddenWrites.push(`${request.method()} ${path}`); return route.abort(); }
        if (path === '/experiments/avatar-motion/') return route.fulfill({ contentType: 'text/html', body: html });
        return route.continue();
      });
      await page.addInitScript(() => {
        window.__formatRuntime = { wasmCalls: 0 };
        for (const name of ['instantiate', 'instantiateStreaming']) { const original = WebAssembly[name];
          if (original) WebAssembly[name] = function (...args) { window.__formatRuntime.wasmCalls++; return Reflect.apply(original, this, args); }; }
      });
      await page.goto(`${base}/experiments/avatar-motion/`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => Boolean(window.OpenVmanAvatar), null, { timeout: 30000 });
      const raw = await browserCase(page, mode);
      result.summary = summarize(raw); result.pageErrors = pageErrors; result.forbiddenWrites = forbiddenWrites;
      await writeFile(join(output, `${name}.json`), JSON.stringify(raw, null, 2));
      await page.screenshot({ path: join(output, `${name}.png`), fullPage: true });
      assert.ok(raw.rvfc.length > 100 && raw.canvasFrames.length > 100, 'Insufficient real decoded/rendered frame evidence');
      assert.equal(raw.runtimeAfter.wasmCalls, raw.runtimeBaseline.wasmCalls, 'WASM was reinitialized');
      assert.equal(raw.markerMismatches.length, 0, 'Decoder marker/JSON timeline mismatch');
      assert.deepEqual(raw.errors, []); assert.deepEqual(pageErrors, []); assert.deepEqual(forbiddenWrites, []);
      assert.equal(raw.decoderLayout.length, mode === 'single-lipsync' ? 1 : 4);
      if (mode === 'single-lipsync') {
        assert.equal(raw.domVideoCount, 1, 'Unexpected standby video');
        assert.ok(raw.audioEvidence.starts.some((entry) => entry.contextState === 'running' && entry.duration >= 18));
        assert.ok(Math.max(...raw.audioEvidence.rms) > .01, 'No real audio signal');
        assert.ok(raw.audioEvidence.mouthPatchDraws > 100, 'No active WASM mouth patch evidence');
        result.audioEvidence = { starts: raw.audioEvidence.starts, peakRms: Math.max(...raw.audioEvidence.rms), mouthPatchDraws: raw.audioEvidence.mouthPatchDraws };
      }
      if (mode === 'mixed-state') { assert.equal(result.summary.actualFormats.length, 2); assert.ok(result.summary.mixedCodecSwitches >= 2); }
      const recording = await page.evaluate(() => window.formatPilot.record());
      await writeFile(join(output, `${name}-proof.webm`), Buffer.from(recording, 'base64'));
      result.recording = `${name}-proof.webm`; result.passed = true;
      console.log(`[PASS] ${name} ${JSON.stringify(result.summary)}`);
    } catch (error) { result.error = error.stack ?? String(error); console.log(`[FAIL] ${name}: ${error.message}`); }
    finally {
      try { await page?.evaluate(() => window.formatPilot?.cleanup()); } catch { /* context close is final fallback */ }
      await context.close(); report.cases.push(result);
      await writeFile(join(output, `${reportPrefix}.json`), JSON.stringify(report, null, 2));
    }
  }
  report.passed = report.cases.length > 0 && report.cases.every((result) => result.passed);
} catch (error) { report.error = error.stack ?? String(error); }
finally {
  await browser?.close(); report.finishedAt = new Date().toISOString();
  await writeFile(join(output, `${reportPrefix}.json`), JSON.stringify(report, null, 2));
  const lines = ['# HCIOT mixed-format pilot', '', `Browser: ${report.browser?.version ?? 'unavailable'}`, '',
    'No recording during measurement; proof recordings run afterwards in the same SDK document.', '',
    '| Case | Pass | Dropped / total | RVFC steady p95 / max ms | Canvas steady p95 / max ms | >200ms steady stalls (RVFC / canvas) | Handoff p95 / max ms | Marker mismatch |',
    '|---|---|---|---|---|---|---|---|'];
  for (const item of report.cases) { const s = item.summary; lines.push(s ? `| ${item.name} | ${item.passed} | ${s.droppedFrames}/${s.totalFrames} | ${s.rvfc.steady.p95Ms?.toFixed(1)}/${s.rvfc.steady.maxMs?.toFixed(1)} | ${s.canvas.steady.p95Ms?.toFixed(1)}/${s.canvas.steady.maxMs?.toFixed(1)} | ${s.rvfc.steady.stallsOver200ms}/${s.canvas.steady.stallsOver200ms} | ${s.handoff.p95Ms}/${s.handoff.maxMs} | ${s.markerMismatches} |` : `| ${item.name} | false | ${item.error?.split('\n')[0]} | | | | | |`); }
  lines.push('', ...report.method.limitations.map((text) => `- ${text}`), '', 'Full raw RVFC/canvas samples and transition timing are in each case JSON. The media marker is checked before display repair against RVFC mediaTime × 25.', '');
  await writeFile(join(output, `${reportPrefix}.md`), lines.join('\n'));
  console.log(`[REPORT] ${join(output, `${reportPrefix}.md`)}`);
}
if (!report.passed) process.exitCode = 1;
