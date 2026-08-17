import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useAudioPlayer.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText.replace(
  /import \{ ref, readonly, onUnmounted \} from ['"]vue['"];?/,
  [
    "const ref = (value) => ({ value });",
    "const readonly = (value) => value;",
    "const onUnmounted = () => undefined;",
  ].join("\n"),
);

const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { useAudioPlayer } = await import(moduleUrl);

test("flush cancels a chunk that is waiting for AudioContext resume", async () => {
  const previousAudioContext = globalThis.AudioContext;
  const previousConsoleWarn = console.warn;

  let resolveResume;
  let playbackResets = 0;
  let playbackStarts = 0;
  let startedSources = 0;
  let forwardedPcm = 0;

  class FakeAudioContext {
    constructor() {
      this.currentTime = 12;
      this.destination = {};
      this.state = "suspended";
    }

    async resume() {
      await new Promise((resolve) => {
        resolveResume = () => {
          this.state = "running";
          resolve();
        };
      });
    }

    createBuffer() {
      return {
        copyToChannel() {},
      };
    }

    createBufferSource() {
      return {
        buffer: null,
        connect() {},
        start() {
          startedSources += 1;
        },
        stop() {},
        onended: null,
      };
    }

    close() {
      this.state = "closed";
    }
  }

  globalThis.AudioContext = FakeAudioContext;
  console.warn = () => undefined;

  try {
    const audio = useAudioPlayer({
      onPcmChunk: () => {
        forwardedPcm += 1;
      },
      onPlaybackReset: () => {
        playbackResets += 1;
      },
      onPlaybackStart: () => {
        playbackStarts += 1;
      },
    });

    const playPromise = audio.playChunk(new Int16Array([1, 2, 3, 4]).buffer);
    assert.equal(typeof resolveResume, "function");

    audio.flush();
    resolveResume();
    await playPromise;

    assert.equal(startedSources, 0);
    assert.equal(forwardedPcm, 0);
    assert.equal(playbackStarts, 0);
    assert.equal(playbackResets, 1);
    assert.equal(audio.isPlaying.value, false);
  } finally {
    globalThis.AudioContext = previousAudioContext;
    console.warn = previousConsoleWarn;
  }
});

test("playback volume is sampled from the audio output graph", async () => {
  const previousAudioContext = globalThis.AudioContext;
  const previousRequestAnimationFrame = globalThis.requestAnimationFrame;
  const previousCancelAnimationFrame = globalThis.cancelAnimationFrame;

  let animationFrameCallback;
  let connectedSourceTarget = null;
  let analyserDestination = null;
  let playbackEnds = 0;
  let playbackStarts = 0;
  let scheduledSource = null;
  const volumes = [];

  class FakeAnalyser {
    constructor() {
      this.fftSize = 4;
    }

    connect(target) {
      analyserDestination = target;
    }

    disconnect() {}

    getByteTimeDomainData(data) {
      data[0] = 128;
      data[1] = 255;
      data[2] = 128;
      data[3] = 1;
    }
  }

  class FakeAudioContext {
    constructor() {
      this.currentTime = 3;
      this.destination = { name: "destination" };
      this.state = "running";
    }

    async resume() {}

    createAnalyser() {
      this.analyser = new FakeAnalyser();
      return this.analyser;
    }

    createBuffer() {
      return {
        copyToChannel() {},
      };
    }

    createBufferSource() {
      scheduledSource = {
        buffer: null,
        connect(target) {
          connectedSourceTarget = target;
        },
        start() {},
        stop() {},
        onended: null,
      };
      return scheduledSource;
    }

    close() {
      this.state = "closed";
    }
  }

  globalThis.AudioContext = FakeAudioContext;
  globalThis.requestAnimationFrame = (callback) => {
    animationFrameCallback = callback;
    return 1;
  };
  globalThis.cancelAnimationFrame = () => undefined;

  try {
    const audio = useAudioPlayer({
      onPlaybackVolume: (volume) => {
        volumes.push(volume);
      },
      onPlaybackEnd: () => {
        playbackEnds += 1;
      },
      onPlaybackStart: () => {
        playbackStarts += 1;
      },
    });

    await audio.playChunk(new Int16Array([1, 2, 3, 4]).buffer);

    assert.ok(connectedSourceTarget instanceof FakeAnalyser);
    assert.equal(analyserDestination?.name, "destination");
    assert.equal(typeof animationFrameCallback, "function");

    animationFrameCallback();

    assert.ok(volumes[0] > 0);
    assert.equal(playbackStarts, 1);

    scheduledSource.onended();
    assert.equal(playbackEnds, 1);
  } finally {
    globalThis.AudioContext = previousAudioContext;
    globalThis.requestAnimationFrame = previousRequestAnimationFrame;
    globalThis.cancelAnimationFrame = previousCancelAnimationFrame;
  }
});
