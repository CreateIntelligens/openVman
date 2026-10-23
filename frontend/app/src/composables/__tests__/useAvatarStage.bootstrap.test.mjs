import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));

// 舞台只透過這兩個模組碰 WASM 與 iframe；換成假的才能在 node 裡跑真正的啟動流程。
const fakeModules = {
  name: "fake-runtime",
  setup(builder) {
    builder.onResolve({ filter: /\/useOpenVmanAvatarRuntime$|\/useStageAvatarBridge$/ }, (args) => ({
      path: args.path, namespace: "fake",
    }));
    builder.onLoad({ filter: /.*/, namespace: "fake" }, (args) => ({
      contents: args.path.endsWith("useOpenVmanAvatarRuntime")
        ? "export const useOpenVmanAvatarRuntime = () => globalThis.__fakeWasm;"
        : `export const useStageAvatarBridge = () => ({
            frameRef: { value: null }, driveMouth() {}, stopMouth() {}, triggerGesture() {},
          });`,
      loader: "js",
    }));
  },
};

const { outputFiles } = await build({
  stdin: {
    contents: `export { useAvatarStage } from "../useAvatarStage";
      export { reactive, ref } from "vue";`,
    resolveDir: __dirname,
    loader: "ts",
  },
  bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
  // 舞台的相依鏈會帶到語音模組；VAD 只在瀏覽器動態載入，測試用不到。
  external: ["@ricky0123/vad-web"],
  plugins: [fakeModules],
});
const { useAvatarStage, reactive, ref } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`
);

const flush = () => new Promise((resolvePromise) => setImmediate(resolvePromise));

function deferred() {
  let resolvePromise;
  const promise = new Promise((resolveInner) => {
    resolvePromise = resolveInner;
  });
  return { promise, resolve: resolvePromise };
}

function createFakeWasm({ initFailures = 0 } = {}) {
  let failuresLeft = initFailures;
  const wasm = {
    isReady: ref(false),
    isLoading: ref(false),
    error: ref(null),
    currentCharId: ref(null),
    currentProjectId: ref(""),
    loads: [],
    initCalls: 0,
    async initWasm() {
      wasm.initCalls += 1;
      if (failuresLeft > 0) {
        failuresLeft -= 1;
        throw new Error("vendor runtime failed");
      }
      wasm.isReady.value = true;
    },
    async loadCharacter(charId, _assetsBase, projectId = "") {
      wasm.loads.push(charId);
      wasm.currentCharId.value = charId;
      wasm.currentProjectId.value = projectId;
    },
    clearAudio() {},
    resetSpeaking() {},
    disposeMotion() {},
  };
  return wasm;
}

function createStage(wasm) {
  globalThis.__fakeWasm = wasm;
  const settings = reactive({
    projectId: "", characterId: "", renderMode: "2d", vrmAvatarId: "",
    backgroundId: "dark", backgroundUrl: "", backgroundFit: "cover",
  });
  const catalogLoads = [];
  const characters = ref([{ id: "0713" }, { id: "1014" }]);
  const bootstrap = {
    avatarCatalog: {
      error: ref(null),
      async load(projectId) {
        catalogLoads.push(projectId);
      },
    },
    characters,
    vrmAvatarOptions: ref([]),
    // 專案確定後挑專案預設 1014；專案還沒回來時只能挑帳號預設 0713。
    pickPreferredCharacterId: (projectId) => (projectId ? "1014" : "0713"),
    preferSaved: (_saved, _isValid, fallback) => fallback,
    accountDefault: (_key, fallback) => fallback,
    addSelectionNotice() {},
    resolveVrmAvatarOption: () => null,
    stageBackgroundFitStyle: () => ({}),
    PREFERRED_CHARACTER_ID: "0713",
  };
  const stage = useAvatarStage(settings, bootstrap);
  return { stage, settings, catalogLoads };
}

test("the stage waits for the project before picking and loading a character", async () => {
  // 開場兩件事同時跑：舞台先用不分專案的清單載了帳號預設 0713，專案回來後設定值
  // 改成專案預設，卻沒有人重新載入，舞台與選單對不上。
  const wasm = createFakeWasm();
  const { stage, settings, catalogLoads } = createStage(wasm);
  const project = deferred();

  const booting = stage.bootstrapRenderer(Promise.resolve(), project.promise);
  await flush();
  assert.deepEqual(wasm.loads, [], "專案決定前不能載入人物");

  settings.projectId = "aws-dev";
  project.resolve();
  await booting;

  assert.deepEqual(wasm.loads, ["1014"]);
  assert.deepEqual(catalogLoads, ["aws-dev"]);
  assert.equal(stage.rendererBootstrapState.value, "ready");
});

test("a transient startup failure retries by itself instead of needing a reload", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const wasm = createFakeWasm({ initFailures: 1 });
  const { stage } = createStage(wasm);

  const booting = stage.bootstrapRenderer(Promise.resolve(), Promise.resolve());
  await flush();
  assert.equal(wasm.initCalls, 1);
  assert.equal(stage.rendererBootstrapState.value, "loading");
  assert.equal(stage.fatalError.value, null, "重試期間不顯示錯誤畫面");

  t.mock.timers.tick(2000);
  await booting;

  assert.equal(wasm.initCalls, 2);
  assert.deepEqual(wasm.loads, ["0713"]);
  assert.equal(stage.rendererBootstrapState.value, "ready");
  assert.equal(stage.fatalError.value, null);
});

test("when the engine never starts the page reloads once, then shows the error", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const storage = new Map();
  let reloads = 0;
  const previousWindow = globalThis.window;
  globalThis.window = {
    location: { reload: () => { reloads += 1; } },
    sessionStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    },
  };
  t.after(() => {
    globalThis.window = previousWindow;
  });

  async function exhaust(stage) {
    const booting = stage.bootstrapRenderer();
    for (const delay of [2000, 4000, 8000]) {
      await flush();
      t.mock.timers.tick(delay);
    }
    await booting;
  }

  const first = createStage(createFakeWasm({ initFailures: 99 }));
  await exhaust(first.stage);
  assert.equal(reloads, 1);
  assert.equal(first.stage.fatalError.value, null);

  // 重新載入後還是失敗：不能無限重新整理，改顯示錯誤讓使用者按重試。
  const second = createStage(createFakeWasm({ initFailures: 99 }));
  await exhaust(second.stage);
  assert.equal(reloads, 1);
  assert.equal(second.stage.fatalError.value?.code, "AVATAR_RENDERER");
});

test("switching project loads the character the new project picked", async () => {
  const wasm = createFakeWasm();
  const { stage, settings } = createStage(wasm);
  await stage.bootstrapRenderer(Promise.resolve(), Promise.resolve());
  assert.deepEqual(wasm.loads, ["0713"]);

  stage.syncCharacter();
  assert.deepEqual(wasm.loads, ["0713"], "同一個人物不重複載入");

  settings.characterId = "1014";
  stage.syncCharacter();
  assert.deepEqual(wasm.loads, ["0713", "1014"]);
});

test("the same character is reloaded when its project motion scope changes", async () => {
  const wasm = createFakeWasm();
  const { stage, settings } = createStage(wasm);
  settings.projectId = "hospital-a";
  await stage.bootstrapRenderer(Promise.resolve(), Promise.resolve());
  const character = wasm.currentCharId.value;
  settings.projectId = "hospital-b";
  stage.syncCharacter();
  assert.deepEqual(wasm.loads, [character, character]);
  assert.equal(wasm.currentProjectId.value, "hospital-b");
});
