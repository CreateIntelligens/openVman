import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

/*
 * 真的把 useAvatarBootstrap、settings store 與 useAuth 跑起來：使用者回報下拉選單
 * 每次打開都回到預設，原因全在時序（清單失敗、載入到一半重整、設定視窗開太早），
 * 比對原始碼字串看不出來。每個案例都用同一份 localStorage 「重開一次」，確認
 * 使用者存的選擇還在。
 */

const __dirname = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(__dirname, "../../..");

const entry = `
export { useAvatarBootstrap } from "./src/composables/useAvatarBootstrap";
export { saveSettings, savedSettings, useSettingsStore } from "./src/stores/useSettingsStore";
export { useAuth } from "./src/composables/useAuth";
export { nextTick } from "vue";
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
  // 共用語音模組動態載入 VAD；這裡用不到，也不在 app 的 node_modules 解析範圍內。
  external: ["@ricky0123/vad-web"],
  logLevel: "error",
});
const bundle = outputFiles[0].text;

const ACCOUNT = "acct1";
const DEFAULTS = {
  project_id: "proj-A",
  character_id: "c1",
  voice_provider: "indextts",
  voice_id: "hayley",
  mascot_id: "",
};
const PERSONAS = { "proj-A": ["default", "pA"], "proj-B": ["default", "pB"] };
const PROVIDERS = [
  { id: "auto", name: "自動", default_voice: "", voices: [] },
  { id: "indextts", name: "IndexTTS", default_voice: "hayley", voices: ["hayley", "amy"] },
  { id: "voxcpm", name: "VoxCPM", default_voice: "v1", voices: ["v1", "v2"] },
];
const MASCOTS = [
  { mascot_id: "qqman", label: "QQ", engine: "3d", vrm_url: "/q.vrm" },
  { mascot_id: "myvrm", label: "Mine", engine: "3d", vrm_url: "/m.vrm" },
];

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const key = (name) => `${name}::${ACCOUNT}`;

let generation = 0;

/** 模擬開一次前台：新的模組實例（store 是模組單例），沿用同一份 localStorage。 */
async function openApp(storage, api = {}) {
  globalThis.window = {
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
      clear: () => storage.clear(),
    },
    location: { pathname: "/", search: "" },
    history: { replaceState() {} },
  };
  globalThis.fetch = async (input) => {
    const url = String(input);
    const path = url.split("?")[0];
    if (api[path]) return api[path](url);
    if (path.endsWith("/api/v1/auth/me")) {
      return json({ id: ACCOUNT, role: "user", username: "u", defaults: DEFAULTS });
    }
    if (path.endsWith("/api/v1/projects")) {
      return json({ projects: [{ project_id: "proj-A" }, { project_id: "proj-B" }] });
    }
    if (path.endsWith("/api/v1/personas")) {
      const pid = new URL(url, "http://x").searchParams.get("project_id");
      return json({ personas: (PERSONAS[pid] ?? []).map((id) => ({ persona_id: id, label: id })) });
    }
    if (path.endsWith("/api/v1/tts/providers")) return json(PROVIDERS);
    if (path.endsWith("/api/v1/avatar/mascots")) return json({ mascots: MASCOTS });
    return json({}, 404);
  };
  generation += 1;
  const url = `data:text/javascript;base64,${Buffer.from(`${bundle}\n//${generation}`).toString("base64")}`;
  const m = await import(url);
  await m.useAuth().bootstrap();
  const settings = m.useSettingsStore();
  const chat = { setProject() {}, setPersona() {} };
  const boot = m.useAvatarBootstrap({ settings, chat: () => chat });
  await m.nextTick();
  return { m, settings, boot };
}

function savedStorage(entries) {
  return new Map(Object.entries(entries).map(([k, v]) => [key(k), v]));
}

test("a failed project list does not erase the saved project or persona", async () => {
  const storage = savedStorage({ "avatar.project_id": "proj-B", "avatar.persona_id": "pB" });

  const first = await openApp(storage, { "/api/v1/projects": () => json({ error: "brain" }, 502) });
  await first.boot.fetchInitialProjectData();
  // 這次沒有清單：先不用任何專案，但存的選擇原封不動。
  assert.equal(first.settings.projectId, "");
  assert.equal(storage.get(key("avatar.project_id")), "proj-B");
  assert.equal(storage.get(key("avatar.persona_id")), "pB");

  const second = await openApp(storage);
  await second.boot.fetchInitialProjectData();
  assert.equal(second.settings.projectId, "proj-B");
  assert.equal(second.settings.personaId, "pB");
});

test("reloading while the project list is still loading keeps the saved project", async () => {
  const storage = savedStorage({ "avatar.project_id": "proj-B", "avatar.persona_id": "pB" });
  const first = await openApp(storage, { "/api/v1/projects": () => new Promise(() => {}) });
  void first.boot.fetchInitialProjectData();
  await sleep(10);
  assert.equal(storage.get(key("avatar.project_id")), "proj-B");

  const second = await openApp(storage);
  await second.boot.fetchInitialProjectData();
  assert.equal(second.settings.projectId, "proj-B");
  assert.equal(second.settings.personaId, "pB");
});

test("opening settings before the project list arrives keeps the saved persona", async () => {
  const storage = savedStorage({ "avatar.project_id": "proj-B", "avatar.persona_id": "pB" });
  const { m, settings, boot } = await openApp(storage, {
    "/api/v1/projects": async () => {
      await sleep(30);
      return json({ projects: [{ project_id: "proj-A" }, { project_id: "proj-B" }] });
    },
  });
  const loading = boot.fetchInitialProjectData();
  await sleep(5);
  // App.vue 的 watch(showSettings)：打開設定就用目前的專案（還是空的）重抓人設。
  await boot.fetchPersonas(settings.projectId, { syncSelected: true });
  await loading;
  await m.nextTick();
  assert.equal(settings.projectId, "proj-B");
  assert.equal(settings.personaId, "pB");
  assert.equal(storage.get(key("avatar.persona_id")), "pB");
});

test("an unauthorized saved project falls back for this session only", async () => {
  const storage = savedStorage({ "avatar.project_id": "proj-gone", "avatar.persona_id": "pB" });
  const { settings, boot } = await openApp(storage);
  await boot.fetchInitialProjectData();
  assert.equal(settings.projectId, "proj-A");
  assert.equal(settings.personaId, "default");
  // 退回的是生效值；存的選擇留著，授權回來時照樣用。
  assert.equal(storage.get(key("avatar.project_id")), "proj-gone");
  assert.equal(storage.get(key("avatar.persona_id")), "pB");
});

test("the saved automatic TTS engine survives a reload", async () => {
  const storage = savedStorage({ "speech.tts_provider": "auto", "speech.tts_voice": "" });
  const { settings, boot } = await openApp(storage);
  await boot.fetchTtsProviders();
  assert.equal(settings.ttsProvider, "auto");
  assert.equal(settings.ttsVoice, "");
});

test("a TTS node missing once does not replace the saved voice", async () => {
  const storage = savedStorage({ "speech.tts_provider": "voxcpm", "speech.tts_voice": "v2" });
  const first = await openApp(storage, {
    "/api/v1/tts/providers": () => json(PROVIDERS.filter((p) => p.id !== "voxcpm")),
  });
  await first.boot.fetchTtsProviders();
  assert.equal(first.settings.ttsProvider, "indextts");
  assert.equal(storage.get(key("speech.tts_provider")), "voxcpm");
  assert.equal(storage.get(key("speech.tts_voice")), "v2");

  const second = await openApp(storage);
  await second.boot.fetchTtsProviders();
  assert.equal(second.settings.ttsProvider, "voxcpm");
  assert.equal(second.settings.ttsVoice, "v2");
});

test("a failed VRM list keeps the saved VRM", async () => {
  const storage = savedStorage({ "avatar.vrm_avatar_id": "myvrm" });
  const first = await openApp(storage, { "/api/v1/avatar/mascots": () => json({}, 502) });
  await first.boot.fetchVrmAvatars();
  assert.equal(first.settings.vrmAvatarId, "myvrm");
  assert.equal(storage.get(key("avatar.vrm_avatar_id")), "myvrm");

  const second = await openApp(storage);
  await second.boot.fetchVrmAvatars();
  assert.equal(second.settings.vrmAvatarId, "myvrm");
});

test("only saveSettings writes, and engine and voice are written as a pair", async () => {
  const storage = new Map();
  const { m, settings } = await openApp(storage);
  settings.projectId = "proj-A";
  await m.nextTick();
  assert.equal(storage.has(key("avatar.project_id")), false);

  m.saveSettings({ ttsProvider: "voxcpm", ttsVoice: "v1" });
  assert.equal(settings.ttsProvider, "voxcpm");
  assert.equal(storage.get(key("speech.tts_provider")), "voxcpm");
  assert.equal(storage.get(key("speech.tts_voice")), "v1");
  assert.equal(m.savedSettings().ttsVoice, "v1");
});
