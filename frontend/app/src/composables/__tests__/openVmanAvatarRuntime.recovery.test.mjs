import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { gzipSync } from "node:zlib";

import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));

// 每個測試各自打包一份，模組層級的單例（runtime、腳本 promise）才不會互相污染。
async function loadRuntimeModule({ captureLifecycle = false } = {}) {
  const { outputFiles } = await build({
    entryPoints: [resolve(__dirname, "../useOpenVmanAvatarRuntime.ts")],
    bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
    plugins: captureLifecycle ? [{
      name: "capture-lifecycle",
      setup(builder) {
        builder.onResolve({ filter: /^vue$/ }, () => ({ path: "vue", namespace: "lifecycle" }));
        builder.onLoad({ filter: /.*/, namespace: "lifecycle" }, () => ({
          contents: `export const ref = value => ({ value });
            export const readonly = value => value;
            export const computed = getter => ({ get value() { return getter(); } });
            export const onUnmounted = callback => globalThis.__runtimeUnmounts.push(callback);`,
          loader: "js",
        }));
      },
    }] : [],
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}#${Math.random()}`
  );
}

function createFakeDom() {
  const scripts = [];
  const document = {
    getElementById: () => null,
    querySelector(selector) {
      if (selector !== 'script[data-dhlive-mini2="true"]') return null;
      return scripts.find((script) => script.connected) ?? null;
    },
    createElement() {
      const listeners = {};
      const script = {
        dataset: {},
        connected: false,
        onload: null,
        onerror: null,
        addEventListener(type, handler) {
          listeners[type] = handler;
        },
        remove() {
          script.connected = false;
        },
        fire(type) {
          script[`on${type}`]?.();
          listeners[type]?.();
        },
      };
      return script;
    },
    body: {
      appendChild(script) {
        script.connected = true;
        scripts.push(script);
      },
    },
  };
  return { document, scripts };
}

function createFakeRuntime() {
  const processed = [];
  let lastWritten = "";
  return {
    processed,
    _malloc: () => 8,
    _free() {},
    stringToUTF8(text) {
      lastWritten = text;
    },
    _processSecret() {
      processed.push(lastWritten);
    },
    _clearAudio() {},
  };
}

function installGlobals(t, { document, runtime, video }) {
  const previous = {
    window: globalThis.window, document: globalThis.document, fetch: globalThis.fetch,
  };
  globalThis.document = document;
  globalThis.window = {
    characterVideo: video,
    createQtAppInstance: undefined,
  };
  t.after(() => {
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.fetch = previous.fetch;
  });
  return {
    makeFactoryAvailable() {
      globalThis.window.createQtAppInstance = async () => runtime;
    },
  };
}

function fakeVideo({ play } = {}) {
  return {
    src: "", loop: false, muted: false, playsInline: false,
    load() {},
    play: play ?? (() => Promise.resolve()),
  };
}

const characterPayload = (name) => gzipSync(Buffer.from(JSON.stringify({ name })));

test("a consumer reusing the connected canvas reinstalls and restores display repair", async (t) => {
  const context = { clearRect() {}, drawImage() {}, getImageData() {} };
  const originalReader = context.getImageData;
  const canvas = { width: 720, height: 1280, isConnected: true, getContext: () => context };
  const { document } = createFakeDom();
  document.getElementById = () => canvas;
  const globals = installGlobals(t, { document, runtime: createFakeRuntime(), video: fakeVideo() });
  globals.makeFactoryAvailable();
  const previous = globalThis.__runtimeUnmounts;
  globalThis.__runtimeUnmounts = [];
  t.after(() => { globalThis.__runtimeUnmounts = previous; });
  const { useOpenVmanAvatarRuntime } = await loadRuntimeModule({ captureLifecycle: true });
  await useOpenVmanAvatarRuntime().initWasm();
  assert.notEqual(context.getImageData, originalReader);
  globalThis.__runtimeUnmounts.shift()();
  assert.equal(context.getImageData, originalReader);

  await useOpenVmanAvatarRuntime().initWasm();
  assert.notEqual(context.getImageData, originalReader);
  globalThis.__runtimeUnmounts.shift()();
  assert.equal(context.getImageData, originalReader);
});

function deferred() {
  let resolvePromise;
  const promise = new Promise((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

test("a failed vendor script is replaced on retry instead of waiting forever", async (t) => {
  // 使用者回報偶爾第一次打不開、重新整理才好：失敗的 <script> 留在頁面上，
  // 重試時等的是早就發生過的 error 事件，永遠不會結束。
  const { document, scripts } = createFakeDom();
  const runtime = createFakeRuntime();
  const globals = installGlobals(t, { document, runtime, video: fakeVideo() });
  const { useOpenVmanAvatarRuntime } = await loadRuntimeModule();
  const avatar = useOpenVmanAvatarRuntime();

  const first = avatar.initWasm();
  scripts[0].fire("error");
  await assert.rejects(first, /Failed to load vendor runtime/);

  const second = avatar.initWasm();
  assert.equal(scripts.length, 2, "重試必須重新插入一個新的 script");
  globals.makeFactoryAvailable();
  scripts[1].fire("load");
  assert.equal(await second, runtime);
  assert.equal(avatar.isReady.value, true);
});

test("loading a character does not wait for video playback to start", async (t) => {
  // 背景分頁的 play() 可能一直不結束；以前會讓畫面卡在「切換展示角色中」。
  const { document, scripts } = createFakeDom();
  const runtime = createFakeRuntime();
  const globals = installGlobals(t, {
    document, runtime, video: fakeVideo({ play: () => new Promise(() => {}) }),
  });
  globalThis.fetch = async () => new Response(characterPayload("1014"));
  const { useOpenVmanAvatarRuntime } = await loadRuntimeModule();
  const avatar = useOpenVmanAvatarRuntime();
  const ready = avatar.initWasm();
  globals.makeFactoryAvailable();
  scripts[0].fire("load");
  await ready;

  await avatar.loadCharacter("1014");

  assert.equal(avatar.isLoading.value, false);
  assert.equal(avatar.currentCharId.value, "1014");
});

test("blocked autoplay notifies the stage and leaves the character loaded", async (t) => {
  const { document } = createFakeDom();
  const blocked = new DOMException("User gesture required", "NotAllowedError");
  const globals = installGlobals(t, {
    document, runtime: createFakeRuntime(), video: fakeVideo({ play: () => Promise.reject(blocked) }),
  });
  globals.makeFactoryAvailable();
  globalThis.fetch = async () => new Response(characterPayload("1014"));
  const { useOpenVmanAvatarRuntime } = await loadRuntimeModule();
  const avatar = useOpenVmanAvatarRuntime();
  const errors = [];
  await avatar.initWasm();
  await avatar.loadCharacter("1014", undefined, undefined, {
    onPlaybackBlocked: (error) => errors.push(error),
  });
  assert.deepEqual(errors, [blocked]);
  assert.equal(avatar.currentCharId.value, "1014");
  assert.equal(avatar.error.value, null);
});

test("character data and video bypass HTTP cache only when requested", async (t) => {
  const { document } = createFakeDom();
  const video = fakeVideo();
  const globals = installGlobals(t, { document, runtime: createFakeRuntime(), video });
  globals.makeFactoryAvailable();
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(characterPayload("1014"));
  };
  const { useOpenVmanAvatarRuntime } = await loadRuntimeModule();
  const avatar = useOpenVmanAvatarRuntime();
  await avatar.initWasm();
  await avatar.loadCharacter("1014");
  assert.equal(requests[0].url, "/static/characters/1014/combined_data.json.gz");
  assert.equal("cache" in requests[0].options, false);
  assert.equal(video.src, "/static/characters/1014/01.webm");

  await avatar.loadCharacter("1014", undefined, undefined, { bypassCache: true });
  assert.equal(requests[1].url, requests[0].url);
  assert.equal(requests[1].options.cache, "reload");
  assert.ok(requests[1].options.signal instanceof AbortSignal);
  assert.match(video.src, /^\/static\/characters\/1014\/01\.webm\?r=\d+$/);
});

test("an older character load that finishes last does not overwrite the newer one", async (t) => {
  // 開場挑人物與使用者切換可能重疊；慢的那個晚回來時不能把舊角色寫回 WASM，
  // 也不能提早把 isLoading 關掉。
  const { document, scripts } = createFakeDom();
  const runtime = createFakeRuntime();
  const globals = installGlobals(t, { document, runtime, video: fakeVideo() });
  const slow = deferred();
  globalThis.fetch = async (url) => (
    String(url).includes("/0713/") ? slow.promise : new Response(characterPayload("1014"))
  );
  const { useOpenVmanAvatarRuntime } = await loadRuntimeModule();
  const avatar = useOpenVmanAvatarRuntime();
  const ready = avatar.initWasm();
  globals.makeFactoryAvailable();
  scripts[0].fire("load");
  await ready;

  const older = avatar.loadCharacter("0713");
  const newer = avatar.loadCharacter("1014");
  await newer;
  assert.equal(avatar.currentCharId.value, "1014");

  slow.resolve(new Response(characterPayload("0713")));
  await older;

  assert.equal(avatar.currentCharId.value, "1014");
  assert.equal(avatar.isLoading.value, false);
  assert.deepEqual(runtime.processed, [JSON.stringify({ name: "1014" })]);
});
