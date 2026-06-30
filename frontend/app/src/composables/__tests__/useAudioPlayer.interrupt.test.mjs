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
    });

    const playPromise = audio.playChunk(new Int16Array([1, 2, 3, 4]).buffer);
    assert.equal(typeof resolveResume, "function");

    audio.flush();
    resolveResume();
    await playPromise;

    assert.equal(startedSources, 0);
    assert.equal(forwardedPcm, 0);
    assert.equal(audio.isPlaying.value, false);
  } finally {
    globalThis.AudioContext = previousAudioContext;
    console.warn = previousConsoleWarn;
  }
});
