import { loadCharacter } from "./character-adapter.mjs";
import { FramePlayer } from "./frame-player.mjs";
import { StreamingPlaybackController } from "./inference/streaming-playback.mjs";

const status = document.querySelector("#status");
const video = document.createElement("video");
video.src = "./assets/character/portrait.webm";
video.muted = video.loop = video.playsInline = true;
const controls = document.querySelectorAll("button");
const fail = (error) => {
  status.textContent = `載入或播放失敗：${error.message}`;
  console.error(error);
};

try {
  const character = await loadCharacter("./assets/character");
  await new Promise((resolve, reject) => {
    if (video.readyState >= 2) return resolve();
    video.addEventListener("loadeddata", resolve, { once: true });
    video.addEventListener("error", () => reject(new Error("影片無法解碼")), {
      once: true,
    });
  });
  const player = new FramePlayer(
    document.querySelector("#stage"),
    video,
    character,
  );
  const audioContext = new AudioContext({ sampleRate: 16000 });
  const recordDestination = audioContext.createMediaStreamDestination();
  const controller = new StreamingPlaybackController({
    audioContext,
    recordDestination,
    onFrame: (frame) => {
      player.controls.set(frame.bsVec);
    },
    onStateChange: (state) => {
      status.textContent = state;
    },
  });
  await controller.initialize({
    workerUrl: "./inference/streaming-worker.js",
    modelPath: new URL("./assets/models/model_audio.onnx", location.href).href,
  });
  let handle = null;
  let feeding = 0;
  const stop = () => {
    feeding++;
    if (handle) controller.stop(handle);
    player.controls.fill(0);
    player.draw();
  };
  const play = async () => {
    stop();
    const thisFeed = feeding;
    await audioContext.resume();
    await video.play();
    const response = await fetch("./assets/speech.wav");
    if (!response.ok) throw new Error("測試語音載入失敗");
    const audio = await audioContext.decodeAudioData(
      await response.arrayBuffer(),
    );
    if (thisFeed !== feeding) return;
    const pcm = Int16Array.from(audio.getChannelData(0), (x) =>
      Math.round(Math.max(-1, Math.min(1, x)) * 32767),
    );
    handle = controller.beginStream({ utteranceId: `demo-${thisFeed}` });
    const feedStarted = performance.now();
    let sequence = 0;
    for (
      let offset = 0;
      offset < pcm.length && thisFeed === feeding;
      offset += 640
    ) {
      const result = controller.appendPcm(handle, {
        sequence: sequence++,
        startSample: offset,
        samples: pcm.slice(offset, offset + 640),
      });
      if (result.accepted === false)
        throw new Error(`PCM rejected: ${result.reason}`);
      // Anchor simulated arrival to PCM time; per-iteration waits accumulate render jitter.
      const nextArrival = feedStarted + Math.min(offset + 640, pcm.length) / 16;
      await new Promise((resolve) =>
        setTimeout(resolve, Math.max(0, nextArrival - performance.now())),
      );
    }
    if (thisFeed === feeding) controller.endStream(handle);
  };
  document.querySelector("#speak").onclick = () => play().catch(fail);
  document.querySelector("#stop").onclick = stop;
  const freeze = async (values = []) => {
    stop();
    player.controls.set(values);
    await player.freeze();
  };
  document.querySelector("#neutral").onclick = () => freeze().catch(fail);
  document.querySelector("#open").onclick = () =>
    freeze([0.35, 0.28]).catch(fail);
  window.demo = {
    player,
    controller,
    play,
    stop,
    freeze,
    audioContext,
    recordDestination,
  };
  player.start();
  await video.play();
  controls.forEach((button) => {
    button.disabled = false;
  });
  status.textContent = "可播放";
  window.addEventListener(
    "pagehide",
    () => {
      controller.dispose();
      player.dispose();
      audioContext.close();
    },
    { once: true },
  );
} catch (error) {
  fail(error);
}
