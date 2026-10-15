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
export { saveSettings, savedSettings, settingsReady, useSettingsStore } from "./src/stores/useSettingsStore";
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
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    const path = url.split("?")[0];
    if (api[path]) return api[path](url, init);
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
    if (path.endsWith("/api/v1/avatar")) {
      return json({
        characters: [
          { char_id: "c1", label: "C1", has_video: true, has_data: true },
          { char_id: "c2", label: "C2", has_video: true, has_data: true },
        ],
      });
    }
    if (path.endsWith("/api/v1/backgrounds")) {
      return json({ backgrounds: [{ background_id: "bg-A" }, { background_id: "bg-B" }] });
    }
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

const PREFS = "/api/v1/settings/my-preferences";

test("settings saved on another device win over this browser", async () => {
  const storage = savedStorage({ "avatar.project_id": "proj-A", "avatar.persona_id": "default" });
  const { m, settings, boot } = await openApp(storage, {
    [PREFS]: async () => {
      await sleep(20);
      return json({ values: { projectId: "proj-B", personaId: "pB", replyMode: "deep" } });
    },
  });
  // App.vue 在 onMounted 先等這個，才開始挑專案。
  await m.settingsReady();
  await boot.fetchInitialProjectData();
  assert.equal(settings.projectId, "proj-B");
  assert.equal(settings.personaId, "pB");
  assert.equal(settings.replyMode, "deep");
  // 也寫回這台當快取，下次後端暫時連不到仍是新的選擇。
  assert.equal(storage.get(key("avatar.project_id")), "proj-B");
});

test("an account with nothing saved uploads what this browser had", async () => {
  const storage = savedStorage({ "avatar.project_id": "proj-B", "avatar.reply_mode": "deep" });
  const sent = [];
  const { m } = await openApp(storage, {
    [PREFS]: (_url, init) => {
      if (init.method === "PUT") {
        sent.push(JSON.parse(init.body).values);
        return json({ values: {} });
      }
      return json({ values: {} });
    },
  });
  await m.settingsReady();
  await sleep(5);
  assert.deepEqual(sent, [{ projectId: "proj-B", replyMode: "deep" }]);
});

test("applying settings saves them to the account", async () => {
  const sent = [];
  const { m } = await openApp(new Map(), {
    [PREFS]: (_url, init) => {
      if (init.method === "PUT") sent.push(JSON.parse(init.body).values);
      return json({ values: {} });
    },
  });
  await m.settingsReady();
  m.saveSettings({ ttsProvider: "voxcpm", ttsVoice: "v1", cameraPreviewScale: 1.2 });
  await sleep(5);
  assert.deepEqual(sent.at(-1), { ttsProvider: "voxcpm", ttsVoice: "v1", cameraPreviewScale: "1.2" });
});

test("a broken preferences endpoint still opens with this browser's settings", async () => {
  const storage = savedStorage({ "avatar.project_id": "proj-B" });
  const { m, settings, boot } = await openApp(storage, { [PREFS]: () => json({ error: "x" }, 502) });
  await m.settingsReady();
  await boot.fetchInitialProjectData();
  assert.equal(settings.projectId, "proj-B");
});

test("someone saved on the hidden live mode opens in standard mode", async () => {
  // 即時模式從設定視窗藏起來了；存著 live 的人要能回到標準模式，不能卡住。
  const storage = savedStorage({ "avatar.voice_mode": "live" });
  const { settings } = await openApp(storage);
  assert.equal(settings.voiceMode, "text");
});

test("switching project falls back to project default resources", async () => {
  const storage = savedStorage({ "avatar.project_id": "proj-A" });
  const { m, settings, boot } = await openApp(storage, {
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: { avatar_character: "c1", avatar_background: "bg-A", avatar_mascot: "qqman" },
      avatar_character: [{ resource_id: "c1", label: "C1", source: "project" }],
      avatar_background: [{ resource_id: "bg-A", label: "BG-A", source: "project" }],
      avatar_mascot: [{ resource_id: "qqman", label: "QQ", source: "project" }],
    }),
    "/api/v1/projects/proj-B/resources": () => json({
      defaults: { avatar_character: "c2", avatar_background: "bg-B", avatar_mascot: "myvrm" },
      avatar_character: [{ resource_id: "c2", label: "C2", source: "project" }],
      avatar_background: [{ resource_id: "bg-B", label: "BG-B", source: "project" }],
      avatar_mascot: [{ resource_id: "myvrm", label: "Mine", source: "project" }],
    }),
  });
  await m.settingsReady();
  await boot.fetchInitialProjectData();
  assert.equal(settings.projectId, "proj-A");
  assert.equal(settings.vrmAvatarId, "qqman");

  // 切換到 proj-B
  await boot.switchProject("proj-B");
  assert.equal(settings.projectId, "proj-B");
  assert.equal(settings.vrmAvatarId, "myvrm");
});

test("legacy saved preferences survive when projectId matches and reset on mismatched project", async () => {
  // 1. 同專案時：舊格式偏好存了 characterId="c2"、vrmAvatarId="myvrm"、backgroundId="uploaded:bg-B"，且 projectId="proj-A"
  const storage1 = savedStorage({
    "avatar.project_id": "proj-A",
    "avatar.character_id": "c2",
    "avatar.vrm_avatar_id": "myvrm",
    "avatar.background_id": "uploaded:bg-B",
  });
  const app1 = await openApp(storage1, {
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: {},
      avatar_character: [
        { resource_id: "c1", label: "C1", source: "project" },
        { resource_id: "c2", label: "C2", source: "project" },
      ],
      avatar_mascot: [
        { resource_id: "qqman", label: "QQ", source: "project" },
        { resource_id: "myvrm", label: "Mine", source: "project" },
      ],
      avatar_background: [
        { resource_id: "bg-A", label: "BG-A", source: "project" },
        { resource_id: "bg-B", label: "BG-B", source: "project" },
      ],
    }),
  });
  await app1.m.settingsReady();
  await app1.boot.fetchInitialProjectData();
  await app1.boot.fetchBackgrounds();
  assert.equal(app1.settings.characterId, "c2");
  assert.equal(app1.settings.vrmAvatarId, "myvrm");
  assert.equal(app1.settings.backgroundId, "uploaded:bg-B");

  // 2. 專案不同時：舊偏好是 proj-B，進入 proj-A 時不沿用 proj-B 的偏好
  const storage2 = savedStorage({
    "avatar.project_id": "proj-B",
    "avatar.character_id": "c2",
    "avatar.vrm_avatar_id": "myvrm",
    "avatar.background_id": "uploaded:bg-B",
  });
  const app2 = await openApp(storage2, {
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: { avatar_character: "c1", avatar_mascot: "qqman", avatar_background: "bg-A" },
      avatar_character: [
        { resource_id: "c1", label: "C1", source: "project" },
        { resource_id: "c2", label: "C2", source: "project" },
      ],
      avatar_mascot: [
        { resource_id: "qqman", label: "QQ", source: "project" },
        { resource_id: "myvrm", label: "Mine", source: "project" },
      ],
      avatar_background: [
        { resource_id: "bg-A", label: "BG-A", source: "project" },
        { resource_id: "bg-B", label: "BG-B", source: "project" },
      ],
    }),
  });
  await app2.m.settingsReady();
  // 強制切到 proj-A
  await app2.boot.switchProject("proj-A");
  assert.equal(app2.settings.characterId, "c1");
  assert.equal(app2.settings.vrmAvatarId, "qqman");
  assert.equal(app2.settings.backgroundId, "uploaded:bg-A");
});

test("four-level selection order for mascots: project pref > project default > account default > catalog first", async () => {
  // 1. 本專案存的偏好優先於專案預設
  const storage1 = savedStorage({
    "avatar.project_id": "proj-A",
    "avatar.vrm_avatar_id::proj::proj-A": "myvrm",
  });
  const app1 = await openApp(storage1, {
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: { avatar_mascot: "qqman" },
      avatar_mascot: [
        { resource_id: "qqman", label: "QQ", source: "project" },
        { resource_id: "myvrm", label: "Mine", source: "project" },
      ],
    }),
  });
  await app1.m.settingsReady();
  await app1.boot.fetchInitialProjectData();
  assert.equal(app1.settings.vrmAvatarId, "myvrm");

  // 2. 專案預設優先於帳號預設
  const storage2 = savedStorage({ "avatar.project_id": "proj-A" });
  const app2 = await openApp(storage2, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, mascot_id: "qqman" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: { avatar_mascot: "myvrm" },
      avatar_mascot: [
        { resource_id: "qqman", label: "QQ", source: "project" },
        { resource_id: "myvrm", label: "Mine", source: "project" },
      ],
    }),
  });
  await app2.m.settingsReady();
  await app2.boot.fetchInitialProjectData();
  assert.equal(app2.settings.vrmAvatarId, "myvrm");

  // 3. 帳號預設優先於清單第一個
  const storage3 = savedStorage({ "avatar.project_id": "proj-A" });
  const app3 = await openApp(storage3, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, mascot_id: "myvrm" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: {},
      avatar_mascot: [
        { resource_id: "qqman", label: "QQ", source: "project" },
        { resource_id: "myvrm", label: "Mine", source: "project" },
      ],
    }),
  });
  await app3.m.settingsReady();
  await app3.boot.fetchInitialProjectData();
  assert.equal(app3.settings.vrmAvatarId, "myvrm");

  // 4. 清單第一個 fallback
  const storage4 = savedStorage({ "avatar.project_id": "proj-A" });
  const app4 = await openApp(storage4, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, mascot_id: "" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: {},
      avatar_mascot: [
        { resource_id: "qqman", label: "QQ", source: "project" },
        { resource_id: "myvrm", label: "Mine", source: "project" },
      ],
    }),
  });
  await app4.m.settingsReady();
  await app4.boot.fetchInitialProjectData();
  assert.equal(app4.settings.vrmAvatarId, "qqman");
});

test("four-level selection order for characters: project pref > project default > account default > catalog first", async () => {
  // 1. 本專案存的偏好優先於專案預設
  const storage1 = savedStorage({
    "avatar.project_id": "proj-A",
    "avatar.character_id::proj::proj-A": "c2",
  });
  const app1 = await openApp(storage1, {
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: { avatar_character: "c1" },
      avatar_character: [
        { resource_id: "c1", label: "C1", source: "project" },
        { resource_id: "c2", label: "C2", source: "project" },
      ],
    }),
  });
  await app1.m.settingsReady();
  await app1.boot.fetchInitialProjectData();
  assert.equal(app1.settings.characterId, "c2");

  // 2. 專案預設優先於帳號預設
  const storage2 = savedStorage({ "avatar.project_id": "proj-A" });
  const app2 = await openApp(storage2, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, character_id: "c1" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: { avatar_character: "c2" },
      avatar_character: [
        { resource_id: "c1", label: "C1", source: "project" },
        { resource_id: "c2", label: "C2", source: "project" },
      ],
    }),
  });
  await app2.m.settingsReady();
  await app2.boot.fetchInitialProjectData();
  assert.equal(app2.settings.characterId, "c2");

  // 3. 帳號預設優先於清單第一個
  const storage3 = savedStorage({ "avatar.project_id": "proj-A" });
  const app3 = await openApp(storage3, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, character_id: "c2" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: {},
      avatar_character: [
        { resource_id: "c1", label: "C1", source: "project" },
        { resource_id: "c2", label: "C2", source: "project" },
      ],
    }),
  });
  await app3.m.settingsReady();
  await app3.boot.fetchInitialProjectData();
  assert.equal(app3.settings.characterId, "c2");

  // 4. 清單第一個 fallback
  const storage4 = savedStorage({ "avatar.project_id": "proj-A" });
  const app4 = await openApp(storage4, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, character_id: "" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: {},
      avatar_character: [
        { resource_id: "c1", label: "C1", source: "project" },
        { resource_id: "c2", label: "C2", source: "project" },
      ],
    }),
  });
  await app4.m.settingsReady();
  await app4.boot.fetchInitialProjectData();
  assert.equal(app4.settings.characterId, "c1");
});

test("four-level selection order for backgrounds: project pref > project default > account default > catalog first", async () => {
  // 1. 本專案存的偏好優先於專案預設
  const storage1 = savedStorage({
    "avatar.project_id": "proj-A",
    "avatar.background_id::proj::proj-A": "uploaded:bg-B",
  });
  const app1 = await openApp(storage1, {
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: { avatar_background: "bg-A" },
      avatar_background: [
        { resource_id: "bg-A", label: "BG-A", source: "project" },
        { resource_id: "bg-B", label: "BG-B", source: "project" },
      ],
    }),
  });
  await app1.m.settingsReady();
  await app1.boot.fetchInitialProjectData();
  await app1.boot.fetchBackgrounds();
  assert.equal(app1.settings.backgroundId, "uploaded:bg-B");

  // 2. 專案預設優先於帳號預設
  const storage2 = savedStorage({ "avatar.project_id": "proj-A" });
  const app2 = await openApp(storage2, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, background_id: "bg-A" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: { avatar_background: "bg-B" },
      avatar_background: [
        { resource_id: "bg-A", label: "BG-A", source: "project" },
        { resource_id: "bg-B", label: "BG-B", source: "project" },
      ],
    }),
  });
  await app2.m.settingsReady();
  await app2.boot.fetchInitialProjectData();
  await app2.boot.fetchBackgrounds();
  assert.equal(app2.settings.backgroundId, "uploaded:bg-B");

  // 3. 帳號預設優先於清單第一個
  const storage3 = savedStorage({ "avatar.project_id": "proj-A" });
  const app3 = await openApp(storage3, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, background_id: "bg-B" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: {},
      avatar_background: [
        { resource_id: "bg-A", label: "BG-A", source: "project" },
        { resource_id: "bg-B", label: "BG-B", source: "project" },
      ],
    }),
  });
  await app3.m.settingsReady();
  await app3.boot.fetchInitialProjectData();
  await app3.boot.fetchBackgrounds();
  assert.equal(app3.settings.backgroundId, "uploaded:bg-B");

  // 4. 清單第一個 fallback
  const storage4 = savedStorage({ "avatar.project_id": "proj-A" });
  const app4 = await openApp(storage4, {
    "/api/v1/auth/me": () => json({
      id: ACCOUNT,
      role: "user",
      username: "u",
      defaults: { ...DEFAULTS, background_id: "" },
    }),
    "/api/v1/projects/proj-A/resources": () => json({
      defaults: {},
      avatar_background: [
        { resource_id: "bg-A", label: "BG-A", source: "project" },
        { resource_id: "bg-B", label: "BG-B", source: "project" },
      ],
    }),
  });
  await app4.m.settingsReady();
  await app4.boot.fetchInitialProjectData();
  await app4.boot.fetchBackgrounds();
  assert.equal(app4.settings.backgroundId, "uploaded:bg-A");
});
