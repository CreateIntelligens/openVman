import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

/*
 * 後台按「試用」後開前台：真的跑開場（settings store、useAuth、bootstrap、舞台、
 * 設定處理函式），再套用交接指令。原本的問題全在時序——登入後伺服器存的偏好
 * 蓋掉後台寫的鍵、專案別偏好優先、沒切到人物所屬的專案——只看原始碼看不出來。
 */

const __dirname = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(__dirname, "../../..");

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

const entry = `
export { useAdminHandoff } from "./src/composables/useAdminHandoff";
export { useAvatarBootstrap } from "./src/composables/useAvatarBootstrap";
export { useAvatarSettings } from "./src/composables/useAvatarSettings";
export { useAvatarStage } from "./src/composables/useAvatarStage";
export { useVisitorMode } from "./src/composables/useVisitorMode";
export { settingsReady, useSettingsStore } from "./src/stores/useSettingsStore";
export { useAuth } from "./src/composables/useAuth";
export { writeAdminHandoff } from "@shared/avatar/adminHandoff";
export { nextTick, ref } from "vue";
`;

const { outputFiles } = await build({
  stdin: { contents: entry, resolveDir: appRoot, loader: "ts" },
  bundle: true,
  write: false,
  platform: "node",
  format: "esm",
  alias: {
    "@shared": resolve(appRoot, "../shared"),
    vue: resolve(appRoot, "node_modules/vue/dist/vue.runtime.esm-bundler.js"),
  },
  define: {
    __VUE_OPTIONS_API__: "true",
    __VUE_PROD_DEVTOOLS__: "false",
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false",
    "process.env.NODE_ENV": '"production"',
  },
  external: ["@ricky0123/vad-web"],
  plugins: [fakeModules],
  logLevel: "error",
});
const bundle = outputFiles[0].text;

const ACCOUNT = "acct1";
const HANDOFF_KEY = "avatar.admin_handoff";
const CHARACTERS = {
  "proj-A": ["c1", "c2"],
  // 專案專屬人物只在它的專案清單裡。
  "proj-B": ["c1", "cB"],
};
const BACKGROUNDS = {
  "proj-A": ["bg-A"],
  "proj-B": ["bg-A", "bg-B"],
};

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const key = (name) => `${name}::${ACCOUNT}`;
const bgUrl = (id) => `/static/backgrounds/${id}/image.png`;

function createFakeWasm() {
  const wasm = {
    isReady: { value: false },
    isLoading: { value: false },
    error: { value: null },
    currentCharId: { value: null },
    loads: [],
    async initWasm() { wasm.isReady.value = true; },
    async loadCharacter(charId) {
      wasm.loads.push(charId);
      wasm.currentCharId.value = charId;
    },
    clearAudio() {},
    resetSpeaking() {},
  };
  return wasm;
}

let generation = 0;

/** 開一次前台並跑完 App.vue onMounted 的開場，回傳之後可以套用交接的各個部分。 */
async function openApp(storage, { serverPrefs = {}, kiosk = false, runBootstrap = true } = {}) {
  const puts = [];
  globalThis.window = {
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
      clear: () => storage.clear(),
    },
    sessionStorage: { getItem: () => null, setItem() {} },
    location: { pathname: "/", search: "", reload() {} },
    history: { replaceState() {} },
  };
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    const path = url.split("?")[0];
    const pid = new URL(url, "http://x").searchParams.get("project_id");
    if (path.endsWith("/api/v1/auth/me")) {
      return json({ id: ACCOUNT, role: "user", username: "u", kiosk, defaults: { project_id: "proj-A" } });
    }
    if (path.endsWith("/api/v1/settings/my-preferences")) {
      if (init.method === "PUT") {
        puts.push(JSON.parse(init.body).values);
        return json({});
      }
      return json({ values: serverPrefs });
    }
    if (path.endsWith("/api/v1/projects")) {
      return json({ projects: [{ project_id: "proj-A" }, { project_id: "proj-B" }] });
    }
    if (path.endsWith("/api/v1/personas")) return json({ personas: [{ persona_id: "default", label: "預設" }] });
    if (path.endsWith("/api/v1/tts/providers")) {
      return json([{ id: "indextts", name: "IndexTTS", default_voice: "hayley", voices: ["hayley"] }]);
    }
    if (path.endsWith("/api/v1/avatar/mascots")) return json({ mascots: [] });
    if (path.endsWith("/api/v1/avatar")) {
      return json({
        characters: (CHARACTERS[pid] ?? ["c1"]).map((id) => ({
          char_id: id, label: `人物 ${id}`, has_video: true, has_data: true,
        })),
      });
    }
    if (path.endsWith("/api/v1/backgrounds")) {
      return json({
        backgrounds: (BACKGROUNDS[pid] ?? []).map((id) => ({ background_id: id, label: id, url: bgUrl(id) })),
      });
    }
    return json({}, 404);
  };
  globalThis.__fakeWasm = createFakeWasm();
  generation += 1;
  const url = `data:text/javascript;base64,${Buffer.from(`${bundle}\n//${generation}`).toString("base64")}`;
  const m = await import(url);
  await m.useAuth().bootstrap();
  const settings = m.useSettingsStore();
  const chat = { setProject() {}, setPersona() {} };
  const boot = m.useAvatarBootstrap({ settings, chat: () => chat });
  const stage = m.useAvatarStage(settings, boot);
  const visitor = m.useVisitorMode();
  const { handleProjectChange } = m.useAvatarSettings(settings, boot, m.ref(false), stage.syncCharacter);
  const { applyAdminHandoff } = m.useAdminHandoff({ settings, bootstrap: boot, stage, visitor, handleProjectChange });
  await m.nextTick();
  if (runBootstrap) {
    // 與 App.vue 的 onMounted 相同順序。
    await m.settingsReady();
    const vrmReady = boot.fetchVrmAvatars();
    const projectReady = boot.fetchInitialProjectData();
    await Promise.allSettled([
      vrmReady, boot.fetchBackgrounds(), projectReady, stage.bootstrapRenderer(vrmReady, projectReady),
    ]);
  }
  return { m, settings, boot, stage, puts, applyAdminHandoff, wasm: globalThis.__fakeWasm };
}

function writeHandoff(storage, payload) {
  storage.set(HANDOFF_KEY, JSON.stringify({ v: 1, accountId: ACCOUNT, createdAt: Date.now(), ...payload }));
}

// 伺服器存的偏好：專案 A、人物 c1、3D 舞台——就是以前蓋掉後台寫入值的那一份。
const SERVER_PREFS = { projectId: "proj-A", characterId: "c1", renderMode: "3d" };

test("試用 switches to the character's owner project and character and saves them", async () => {
  const storage = new Map();
  writeHandoff(storage, { projectId: "proj-B", characterId: "cB" });
  const app = await openApp(storage, { serverPrefs: SERVER_PREFS });
  assert.equal(app.settings.projectId, "proj-A");
  assert.equal(app.settings.characterId, "c1");

  await app.applyAdminHandoff();

  assert.equal(storage.has(HANDOFF_KEY), false);
  assert.equal(app.settings.projectId, "proj-B");
  assert.equal(app.settings.characterId, "cB");
  assert.equal(app.settings.renderMode, "2d");
  assert.equal(app.wasm.loads.at(-1), "cB");
  assert.equal(storage.get(key("avatar.project_id")), "proj-B");
  assert.equal(storage.get(key("avatar.character_id")), "cB");
  assert.equal(storage.get(key("avatar.character_id::proj::proj-B")), "cB");
  assert.equal(storage.get(key("avatar.render_mode")), "2d");
  // 也送回伺服器，換台電腦或重新整理不會又被舊偏好蓋回去。
  assert.ok(app.puts.some((values) => values.characterId === "cB"));
  assert.ok(app.puts.some((values) => values.projectId === "proj-B"));
  assert.deepEqual(app.boot.selectionNotices.value, []);

  // 再開一次前台：指令已經用掉，留下的是存好的選擇。
  const again = await openApp(storage, {
    serverPrefs: { projectId: "proj-B", characterId: "cB", renderMode: "2d" },
  });
  await again.applyAdminHandoff();
  assert.equal(again.settings.projectId, "proj-B");
  assert.equal(again.settings.characterId, "cB");
});

for (const [name, payload, options] of [
  ["another account", { accountId: "someone-else" }, {}],
  ["an expired handoff", { createdAt: Date.now() - 121_000 }, {}],
  ["a locked kiosk", {}, { kiosk: true }],
]) {
  test(`${name} changes nothing and still consumes the handoff`, async () => {
    const storage = new Map();
    writeHandoff(storage, { projectId: "proj-B", characterId: "cB", backgroundId: "uploaded:bg-B", ...payload });
    const app = await openApp(storage, { serverPrefs: SERVER_PREFS, ...options });

    await app.applyAdminHandoff();

    assert.equal(storage.has(HANDOFF_KEY), false);
    assert.equal(app.settings.projectId, "proj-A");
    assert.equal(app.settings.characterId, "c1");
    assert.equal(app.settings.renderMode, "3d");
    assert.notEqual(app.settings.backgroundId, "uploaded:bg-B");
    assert.equal(storage.get(key("avatar.character_id")), "c1");
    assert.deepEqual(app.puts, []);
    assert.deepEqual(app.boot.selectionNotices.value, []);
  });
}

test("a character outside the project's list only leaves a fixed notice", async () => {
  const storage = new Map();
  writeHandoff(storage, { characterId: "<b>ghost</b>" });
  const app = await openApp(storage, { serverPrefs: SERVER_PREFS });

  await app.applyAdminHandoff();

  assert.equal(storage.has(HANDOFF_KEY), false);
  assert.equal(app.settings.characterId, "c1");
  assert.deepEqual(app.puts, []);
  assert.equal(app.boot.selectionNotices.value.length, 1);
  assert.ok(!app.boot.selectionNotices.value[0].includes("ghost"));
});

test("a project the account cannot use stops before touching anything", async () => {
  const storage = new Map();
  writeHandoff(storage, { projectId: "proj-X", characterId: "c2" });
  const app = await openApp(storage, { serverPrefs: SERVER_PREFS });

  await app.applyAdminHandoff();

  assert.equal(app.settings.projectId, "proj-A");
  assert.equal(app.settings.characterId, "c1");
  assert.deepEqual(app.puts, []);
  assert.equal(app.boot.selectionNotices.value.length, 1);
  assert.ok(!app.boot.selectionNotices.value[0].includes("proj-X"));
});

test("a background is applied with the URL from the server list, not the handoff", async () => {
  const storage = new Map();
  writeHandoff(storage, {
    projectId: "proj-B", backgroundId: "uploaded:bg-B", backgroundUrl: "https://elsewhere.invalid/x.png",
  });
  const app = await openApp(storage, { serverPrefs: SERVER_PREFS });

  await app.applyAdminHandoff();

  assert.equal(app.settings.projectId, "proj-B");
  assert.equal(app.settings.backgroundId, "uploaded:bg-B");
  assert.equal(app.settings.backgroundUrl, bgUrl("bg-B"));
  assert.equal(storage.get(key("avatar.background_url")), bgUrl("bg-B"));
  assert.equal(storage.get(key("avatar.background_id::proj::proj-B")), "uploaded:bg-B");
  // 沒指定人物就不動舞台模式。
  assert.equal(app.settings.renderMode, "3d");
});

test("a background outside the list is ignored with a notice", async () => {
  const storage = new Map();
  writeHandoff(storage, { backgroundId: "uploaded:bg-B", backgroundUrl: bgUrl("bg-B") });
  const app = await openApp(storage, { serverPrefs: SERVER_PREFS });

  await app.applyAdminHandoff();

  assert.notEqual(app.settings.backgroundId, "uploaded:bg-B");
  assert.equal(app.boot.selectionNotices.value.length, 1);
});

test("a stage still loading (about to reload the page) leaves the handoff for after the reload", async () => {
  const storage = new Map();
  writeHandoff(storage, { characterId: "c2" });
  const app = await openApp(storage, { serverPrefs: SERVER_PREFS, runBootstrap: false });

  await app.applyAdminHandoff();

  assert.equal(storage.has(HANDOFF_KEY), true);
  assert.notEqual(app.settings.characterId, "c2");
});

test("App.vue applies the handoff once the initial bootstrap has settled", () => {
  const app = readFileSync(resolve(appRoot, "src/App.vue"), "utf8");
  assert.match(app, /useAdminHandoff\(\{[^}]*handleProjectChange[^}]*\}\)/);
  assert.match(app, /stage\.bootstrapRenderer\(vrmReady, projectReady\),\s*\]\)\.then\(applyAdminHandoff\)/);
});
