import { MotionSegmentPlayer, waitForDecodedFrame } from "./motion-controller.js";
import { installSpeakerTap } from "./recording-audio.js";
import { checkMotionAccess } from "./access-check.js";
import { MotionVideoCache } from "./video-cache.js";
import { labels, motionSource, segments, validateMotionManifest } from "./motion-source.js";

const $ = (id) => document.getElementById(id);
const held = $("held-frame");
const errors = [];
let avatar, player, loaded = false, frozen = false, frames = 0, run = 0;
let rendition = "original", renditionUrl;
let videoCache, lastRenderedVideo, fade = 0;
let access = "checking", accessCheck;
let audioBytes, recorder, recordStream, recordingUrl;
let recordingOperation = Promise.resolve();
let recordStarted = 0, recordTimer, recordingError = "";
let resolveReady, rejectReady;
const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
ready.catch(() => {});

// This isolated lab taps the SDK's real speaker output for MediaRecorder.
// The normal application and the SDK itself are not modified.
const speakerTap = installSpeakerTap();

const originalDraw = CanvasRenderingContext2D.prototype.drawImage;
CanvasRenderingContext2D.prototype.drawImage = function (source, ...args) {
  const result = originalDraw.call(this, source, ...args);
  if (this.canvas.id === "canvas_video" && source === window.characterVideo) {
    frames += 1;
    lastRenderedVideo = source;
  }
  return result;
};

function showError(error) {
  const message = error instanceof Error ? error.message : String(error);
  errors.push(message);
  $("error").textContent = message;
  $("error").hidden = false;
  $("retry").hidden = false;
  $("status").textContent = "測試暫停，請重新載入後再試。";
}

function abortError() { return new DOMException("取消", "AbortError"); }
function wait(ms, revision) {
  return new Promise((resolve) => setTimeout(() => resolve(revision === run), ms));
}

function waitForRenderedFrame(signal, video = window.characterVideo) {
  const first = frames;
  const started = performance.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      if (signal?.aborted) return reject(abortError());
      // This RAF runs after the synchronous WASM draw/mouth patch has returned.
      // Observe the selected decoder, rather than waiting a fixed two frames.
      if (frames > first && lastRenderedVideo === video) return resolve();
      if (performance.now() - started > 4000) return reject(new Error("對嘴引擎沒有呈現新畫面"));
      requestAnimationFrame(tick);
    };
    tick();
  });
}

function freezeFrame() {
  const canvas = $("canvas_video"), context = held.getContext("2d");
  if (frozen) {
    context.globalCompositeOperation = "destination-in";
    context.globalAlpha = Number(held.style.opacity);
    context.fillRect(0, 0, held.width, held.height);
    context.globalAlpha = 1;
    context.globalCompositeOperation = "destination-over";
    context.drawImage(canvas, 0, 0);
    context.globalCompositeOperation = "source-over";
  } else {
    held.width = canvas.width;
    held.height = canvas.height;
    held.getContext("2d").drawImage(canvas, 0, 0);
  }
  frozen = true;
  fade = 0;
  held.style.transition = "none";
  held.style.opacity = "1";
}

async function revealFrame(signal) {
  const started = performance.now();
  await new Promise((resolve, reject) => {
    const tick = (now) => {
      if (signal.aborted) return reject(abortError());
      const progress = Math.min(1, (now - started) / 180);
      fade = progress * progress * (3 - 2 * progress);
      held.style.opacity = String(1 - fade);
      if (progress === 1) return resolve();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  frozen = false;
}

async function createCachedVideo(source) {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  video.hidden = true;
  document.body.appendChild(video);
  try {
    await new Promise((resolve, reject) => {
      const finish = (error) => {
        clearTimeout(timer);
        video.removeEventListener("loadeddata", loaded);
        video.removeEventListener("error", failed);
        error ? reject(error) : resolve();
      };
      const loaded = () => finish();
      const failed = () => finish(new Error("待命影片無法解碼"));
      const timer = setTimeout(() => finish(new Error("待命影片載入逾時")), 15000);
      video.addEventListener("loadeddata", loaded);
      video.addEventListener("error", failed);
      video.src = source;
      video.load();
    });
    return video;
  } catch (error) {
    video.removeAttribute("src");
    video.load();
    video.remove();
    throw error;
  }
}

function updateState(state) {
  $("stage-state").textContent = labels[state];
  $("metric-state").textContent = labels[state];
  document.querySelectorAll("[data-state]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.state === state));
  });
  const { start, end } = segments[state];
  $("segment-description").textContent = `${labels[state]}：${segments[state].clip} · ${start.toFixed(2)}–${end.toFixed(2)} 秒${segments[state].loop === false ? " · 播完回待機" : ""}`;
  $("status").textContent = `正在播放${labels[state]}區段`;
}

async function refreshAccess() {
  if (accessCheck) return accessCheck;
  accessCheck = (async () => {
    $("load").disabled = true;
    $("check-access").disabled = true;
    const result = await checkMotionAccess(fetch, motionSource.dataUrl);
    access = result.state;
    document.body.dataset.access = access;
    $("access").hidden = access === "available";
    $("access-message").textContent = result.message;
    $("status").textContent = result.message;
    $("load").hidden = access !== "available";
    $("load").disabled = access !== "available";
    $("check-access").disabled = false;
    return access;
  })();
  try { return await accessCheck; } finally { accessCheck = null; }
}

async function load() {
  $("load").disabled = true;
  try {
    // A session may expire after the initial check. Recheck before starting
    // the SDK, because a failed load can dispose the same-document runtime.
    if (await refreshAccess() !== "available") return;
    $("load").disabled = true;
    $("status").textContent = "正在載入角色、影片與逐幀資料…";
    if (!window.OpenVmanAvatar) throw new Error("SDK 未載入，請確認站台連線。");
    const manifest = await fetch(motionSource.manifestUrl);
    if (!manifest.ok) throw new Error("HCIOT 動作素材尚未部署，請確認素材準備工作已完成。");
    validateMotionManifest(await manifest.json());
    // Finish the whole-file fetch before the SDK opens a media Range request
    // for the same URL; a failed preload must not consume the one-shot runtime.
    $("status").textContent = "正在預載四段動作影片…";
    try {
      const fastVideo = await fetch(motionSource.videoUrl, { cache: "no-store" });
      if (!fastVideo.ok) throw new Error(`HTTP ${fastVideo.status}`);
      renditionUrl = URL.createObjectURL(await fastVideo.blob());
    } catch (error) {
      throw new Error(`動作影片預載失敗，請重新載入後再試（${error.message}）。`);
    }
    avatar = await window.OpenVmanAvatar.init({ characterId: motionSource.id,
      assetsBaseUrl: motionSource.assetsBaseUrl, container: $("avatar"), zIndex: 0 });
    {
      $("status").textContent = "正在準備快速切換影片…";
      const video = window.characterVideo;
      const canPlay = new Promise((resolve, reject) => {
        const finish = (error) => {
          clearTimeout(timer);
          video.removeEventListener("loadeddata", loadedData);
          video.removeEventListener("error", failed);
          error ? reject(error) : resolve();
        };
        const loadedData = () => finish();
        const failed = () => finish(new Error("快速切換影片無法解碼"));
        const timer = setTimeout(() => finish(new Error("快速切換影片載入逾時")), 15000);
        video.addEventListener("loadeddata", loadedData);
        video.addEventListener("error", failed);
      });
      video.src = renditionUrl;
      video.load();
      await canPlay;
      await video.play();
      rendition = "hciot-entry-keyframes";
    }
    await waitForRenderedFrame();
    if (renditionUrl) {
      $("status").textContent = "正在預備動作起始畫面…";
      videoCache = new MotionVideoCache(window.characterVideo, segments, {
        createVideo: createCachedVideo,
        maxEntries: navigator.deviceMemory && navigator.deviceMemory <= 4 ? 2 : 3,
      });
      try { await videoCache.warm(); }
      catch {
        // Some mobile browsers limit simultaneous decoders. Keep one video
        // usable when standby decoding is unavailable.
        videoCache.dispose({ keepActive: true });
        videoCache = null;
      }
    }
    player = new MotionSegmentPlayer(window.characterVideo, segments, {
      beforeSeek() { if (!videoCache) freezeFrame(); },
      ...(videoCache ? {
        acquireVideo: (state, signal) => videoCache.acquire(state, signal),
        activateVideo(video, state) {
          freezeFrame();
          window.characterVideo = video;
          videoCache.activate(video, state, { deferRefill: true });
        },
      } : {}),
      async afterSeek(state, signal, video) {
        await waitForDecodedFrame(video, signal, segments[state]);
        await waitForRenderedFrame(signal, video);
        if (signal.aborted) throw abortError();
        await revealFrame(signal);
        void videoCache?.refill()?.catch(showError);
      },
      onChange: updateState,
      onError: showError,
    });
    await player.setState("idle");
    // Fetch the committed sample once; every later run remains entirely local.
    const response = await fetch("./sample.wav");
    if (!response.ok) {
      throw new Error("測試語音未部署，請重新整理或通知維護者。");
    }
    audioBytes = await response.arrayBuffer();
    const signature = new TextDecoder().decode(new Uint8Array(audioBytes, 0, Math.min(12, audioBytes.byteLength)));
    if (signature.slice(0, 4) !== "RIFF" || signature.slice(8, 12) !== "WAVE") {
      throw new Error("測試語音格式不正確，請確認部署檔案。");
    }
    loaded = true;
    $("load").hidden = true;
    document.querySelectorAll("button:disabled,input:disabled").forEach((element) => { element.disabled = false; });
    resolveReady();
  } catch (error) {
    showError(error);
    rejectReady(error);
  }
}

async function setState(state) {
  if (!loaded) throw new Error("請先載入測試角色");
  run += 1;
  avatar.interrupt();
  return player.setState(state);
}

async function speak() {
  const revision = ++run;
  avatar.interrupt();
  if (!await player.setState("speaking") || revision !== run) return;
  await avatar.playAudio(audioBytes.slice(0));
  if (revision === run) await player.setState("idle");
}

async function runCycle() {
  if (!loaded) throw new Error("請先載入測試角色");
  const revision = ++run;
  avatar.interrupt();
  if (!await player.setState("idle") || !await wait(600, revision)) return;
  if (!await playGesture("greeting", revision)) return;
  if (!await player.setState("thinking") || !await wait(7000, revision)) return;
  if (revision !== run || !await player.setState("speaking")) return;
  if (revision !== run) return;
  await avatar.playAudio(audioBytes.slice(0));
  if (revision !== run) return;
  if (!await playGesture("bye", revision)) return;
  await wait(1000, revision);
}

async function playGesture(state, revision) {
  if (!await player.setState(state) || revision !== run) return false;
  const deadline = performance.now() + 15000;
  while (revision === run) {
    if (player.state === "idle" && !player.transitioning) return true;
    if (performance.now() > deadline) throw new Error(`${labels[state]}動作未能完成`);
    if (!await wait(50, revision)) return false;
  }
  return false;
}

async function stop() {
  run += 1;
  avatar?.interrupt();
  if (player) await player.setState("idle", "stop");
}

function silenceWav() {
  const buffer = new ArrayBuffer(44 + 1600 * 2), view = new DataView(buffer);
  const text = (offset, value) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF"); view.setUint32(4, buffer.byteLength - 8, true); text(8, "WAVEfmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); text(36, "data"); view.setUint32(40, 3200, true);
  return buffer;
}

const recordingCanvas = document.createElement("canvas");
recordingCanvas.width = 960;
recordingCanvas.height = 960;
const recordingContext = recordingCanvas.getContext("2d");
function paintRecordingFrame() {
  const context = recordingContext, canvas = $("canvas_video");
  context.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--panel");
  context.fillRect(0, 0, 960, 960);
  if (canvas?.width && canvas.height) {
    const scale = Math.min(960 / canvas.width, 850 / canvas.height);
    context.drawImage(canvas, (960 - canvas.width * scale) / 2, 60, canvas.width * scale, canvas.height * scale);
    if (frozen) {
      context.globalAlpha = 1 - fade;
      context.drawImage(held, (960 - held.width * scale) / 2, 60, held.width * scale, held.height * scale);
      context.globalAlpha = 1;
    }
  }
  context.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text");
  context.font = "600 28px system-ui";
  context.fillText(`openVman · HCIOT 動作測試 · ${labels[player?.state] ?? "載入中"}`, 30, 42);
  context.font = "20px system-ui";
  context.fillText("四段動作素材 · 說話使用等待指令影片對嘴", 30, 935);
}
let lastComposite = 0;
function composite(now) {
  if (recorder?.state === "recording" && now - lastComposite >= 40) {
    paintRecordingFrame();
    lastComposite = now;
  }
  requestAnimationFrame(composite);
}
requestAnimationFrame(composite);

function queueRecording(operation) {
  const pending = recordingOperation.then(operation);
  recordingOperation = pending.catch(() => {});
  return pending;
}

function startRecording() { return queueRecording(beginRecording); }
async function beginRecording() {
  if (!loaded) throw new Error("請先載入測試角色");
  if (!window.MediaRecorder || !recordingCanvas.captureStream) throw new Error("此瀏覽器不支援錄影");
  if (recorder?.state === "recording") return;
  // Initialize the SDK AudioContext within the user's gesture before taking
  // its audio track; adding tracks after MediaRecorder.start is unreliable.
  if (!speakerTap.getStream()) await avatar.playAudio(silenceWav());
  const mimeType = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"]
    .find((type) => MediaRecorder.isTypeSupported(type));
  paintRecordingFrame();
  recordStream = recordingCanvas.captureStream(25);
  for (const track of speakerTap.getStream()?.getAudioTracks() ?? []) recordStream.addTrack(track.clone());
  if (!recordStream.getAudioTracks().length) throw new Error("無法擷取測試語音，錄影尚未開始");
  recorder = new MediaRecorder(recordStream, mimeType ? { mimeType } : undefined);
  const current = recorder;
  recordingError = "";
  current.addEventListener("error", (event) => {
    recordingError = event.error?.message ?? "錄影編碼失敗";
    showError(new Error(recordingError));
  });
  current.chunks = [];
  current.addEventListener("dataavailable", (event) => { if (event.data.size) current.chunks.push(event.data); });
  const firstData = new Promise((resolve, reject) => {
    const finish = (error) => {
      clearTimeout(timer);
      current.removeEventListener("dataavailable", data);
      current.removeEventListener("error", failed);
      error ? reject(error) : resolve();
    };
    const data = (event) => { if (event.data.size) finish(); };
    const failed = () => finish(new Error("錄影無法啟動"));
    const timer = setTimeout(() => finish(new Error("錄影沒有產生畫面資料")), 6000);
    current.addEventListener("dataavailable", data);
    current.addEventListener("error", failed);
  });
  recorder.start(250);
  recordStarted = performance.now();
  $("record").textContent = "停止錄影";
  recordTimer = setTimeout(() => void stopRecording(), 120000);
  await firstData;
}

function stopRecording() { return queueRecording(finishRecording); }
async function finishRecording() {
  if (!recorder || recorder.state !== "recording") return null;
  clearTimeout(recordTimer);
  const current = recorder;
  const currentStream = recordStream;
  const blob = await new Promise((resolve) => {
    current.addEventListener("stop", () => resolve(new Blob(current.chunks, { type: current.mimeType })), { once: true });
    current.stop();
  });
  currentStream.getTracks().forEach((track) => track.stop());
  if (recordingUrl) URL.revokeObjectURL(recordingUrl);
  recordingUrl = URL.createObjectURL(blob);
  $("download").href = recordingUrl;
  $("download").hidden = false;
  $("record").textContent = "開始錄影";
  return blob;
}

window.motionDemo = {
  ready, setState, runCycle, stop, startRecording, stopRecording,
  snapshot: () => ({ ready: loaded, access, state: player?.state ?? "idle", transitioning: player?.transitioning ?? false,
    loops: player?.loops ?? 0, transitions: player?.transitions ?? [], errors: [...errors, ...(player?.errors ?? [])],
    frameCount: frames, currentFrame: Math.floor((window.characterVideo?.currentTime ?? 0) * 25),
    source: motionSource.id, rendition, videoCache: videoCache?.snapshot() ?? null,
    duration: window.characterVideo?.duration ?? 0, segments, recording: recorder?.state === "recording",
    recordingMs: recorder?.state === "recording" ? performance.now() - recordStarted : 0,
    recordingError, recordedBytes: recorder?.chunks?.reduce((sum, chunk) => sum + chunk.size, 0) ?? 0,
    recordingTracks: recordStream?.getTracks().map((track) => ({ kind: track.kind, readyState: track.readyState, enabled: track.enabled })) ?? [] }),
};

$("load").addEventListener("click", () => void load());
$("check-access").addEventListener("click", () => void refreshAccess());
$("retry").addEventListener("click", () => location.reload());
document.querySelectorAll("[data-state]").forEach((button) => button.addEventListener("click", () => {
  void (button.dataset.state === "speaking" ? speak() : setState(button.dataset.state)).catch(showError);
}));
$("cycle").addEventListener("click", () => void runCycle().catch(showError));
$("stop").addEventListener("click", () => void stop().catch(showError));
$("record").addEventListener("click", () => void (recorder?.state === "recording" ? stopRecording() : startRecording()).catch(showError));
$("audio").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) return showError(new Error("音訊請小於 20 MB"));
  await stop();
  audioBytes = await file.arrayBuffer();
  $("status").textContent = `已選擇 ${file.name}；按「說話」播放。`;
});
setInterval(() => {
  if (!player) return;
  $("metric-loops").textContent = String(player.loops);
  $("metric-frames").textContent = String(frames);
  const last = player.transitions.at(-1);
  if (last) $("metric-latency").textContent = `${last.ms} ms`;
  const cache = videoCache?.snapshot();
  $("metric-cache").textContent = cache ? `${cache.hits} 次／待命 ${cache.entries} 段` : "單播放器";
  $("events").replaceChildren(...player.transitions.slice(-8).reverse().map((entry) => {
    const item = document.createElement("li");
    item.textContent = `${labels[entry.state]} · ${entry.reason === "loop" ? "循環" : "切換"} · ${entry.ms} ms`;
    return item;
  }));
}, 300);
window.addEventListener("pagehide", () => {
  run += 1;
  player?.dispose();
  videoCache?.dispose();
  avatar?.destroy();
  if (recorder?.state === "recording") recorder.stop();
  recordStream?.getTracks().forEach((track) => track.stop());
  if (renditionUrl) URL.revokeObjectURL(renditionUrl);
  speakerTap.restore();
  CanvasRenderingContext2D.prototype.drawImage = originalDraw;
});
void refreshAccess();
