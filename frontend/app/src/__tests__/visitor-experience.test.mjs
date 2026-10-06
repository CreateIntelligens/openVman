import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(resolve(__dirname, path), "utf8");
async function load(path, replacements = []) {
  let source = read(path);
  for (const [from, to] of replacements) source = source.replace(from, to);
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

// vue 在 data: URL 裡解析不到，換成最小的 ref／computed 就能測純邏輯。
const fakeVue = `const ref = (value) => ({ value });
const computed = (get) => ({ get value() { return get(); } });`;
const { readKioskFlag } = await load("../composables/useVisitorMode.ts", [
  [/import \{ computed, ref \} from "vue";/, fakeVue],
  [/import \{ useAuth \} from "\.\/useAuth";/, "const useAuth = () => ({ account: { value: null } });"],
]);
const { suggestedQuestions } = await load("../components/controls/quickQaText.ts");
const app = read("../App.vue");

test("visitor mode is turned on and off from the URL and remembered for the device", () => {
  assert.equal(readKioskFlag("?kiosk=1", null), true);
  assert.equal(readKioskFlag("?project=a&kiosk=true", null), true);
  assert.equal(readKioskFlag("?kiosk=0", "1"), false);
  assert.equal(readKioskFlag("", "1"), true);
  assert.equal(readKioskFlag("", null), false);
});

test("the start screen only appears in visitor mode and starts listening after the tap", () => {
  assert.match(app, /const started = ref\(!visitor\.kiosk\.value\)/);
  assert.match(app, /<StartOverlay\s+v-if="!started"/);
  assert.match(app, /await handleStart\(\)/);
  assert.match(app, /handleAsrToggle\(\)/);
  assert.match(app, /:settings-visible="visitor\.settingsVisible\.value"/);
  // 來賓不能按到登出：帳號列跟設定一起藏。
  assert.match(read("../Root.vue"), /<div v-if="visitor\.settingsVisible\.value" class="session-toolbar">/);
});

const tree = [
  { node_id: "en", label: "English", order: 0, children: [
    { node_id: "en-hours", label: "Hours", qa_entries: [{ question: "When do you open?" }] },
  ] },
  { node_id: "zh", label: "中文", order: 1, children: [
    { node_id: "t1", label: "營業", order: 1, qa_entries: [
      { question: "隱藏題", hidden: true },
      { question: "幾點開門？", source_path: "knowledge/qa/a.md" },
    ] },
    { node_id: "t0", label: "產品", order: 0, qa_entries: [{ question: "有哪些型號？" }] },
    { node_id: "t2", label: "停用", hidden: true, qa_entries: [{ question: "不該出現" }] },
  ] },
];

test("suggestions take one visible question per topic from the Chinese category", () => {
  assert.deepEqual(suggestedQuestions(tree), [
    { label: "有哪些型號？", message: "產品 有哪些型號？", sourcePath: undefined },
    { label: "幾點開門？", message: "營業 幾點開門？", sourcePath: "knowledge/qa/a.md" },
  ]);
  assert.equal(suggestedQuestions(tree, 1).length, 1);
  // 只有一個主題時從同一類往下拿，不會只有一題（鶴記 94 題都在同一類）。
  const single = [{ node_id: "zh", label: "中文", children: [
    { node_id: "faq", label: "型錄", qa_entries: ["一", "二", "三", "四", "五"].map((q) => ({ question: q })) },
  ] }];
  assert.deepEqual(suggestedQuestions(single).map((item) => item.label), ["一", "二", "三", "四"]);
  assert.deepEqual(suggestedQuestions(undefined), []);
});

test("the chat panel shows suggestions before the first question and a live mic meter", () => {
  const panel = read("../components/chat/ChatPanel.vue");
  assert.match(panel, /v-if="!compact && messages\.length === 0 && suggestions\.length"/);
  assert.match(panel, /emit\('suggest', item\.message, item\.sourcePath\)/);
  assert.match(panel, /<MicLevel v-if="asrListening"/);
  assert.match(app, /@suggest="handleSend"/);
  assert.match(app, /useMicLevel\(computed\(\(\) => activeAsr\.value\.isListening\.value\)\)/);
});

test("an idle kiosk resets for the next visitor, but never mid-answer", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const listeners = {};
  globalThis.window = {
    addEventListener: (name, fn) => { listeners[name] = fn; },
    removeEventListener: () => {},
  };
  const { useIdleReset } = await load("../composables/useIdleReset.ts", [
    [/import \{ onUnmounted, watch \} from "vue";/,
      "const onUnmounted = () => {}; const watch = (_s, cb, o) => { globalThis.__rerun = cb; if (o?.immediate) cb(); };"],
  ]);
  const state = { enabled: true, busy: false, resets: 0 };
  useIdleReset({
    enabled: () => state.enabled,
    busy: () => state.busy,
    activity: () => 0,
    timeoutMs: 1000,
    onIdle: () => { state.resets += 1; },
  });

  t.mock.timers.tick(900);
  listeners.pointerdown();          // 來賓點了畫面：重新計時
  t.mock.timers.tick(900);
  assert.equal(state.resets, 0);

  state.busy = true;                // 虛擬人在回答：不算閒置
  globalThis.__rerun();
  t.mock.timers.tick(5000);
  assert.equal(state.resets, 0);

  state.busy = false;
  globalThis.__rerun();
  t.mock.timers.tick(1000);
  assert.equal(state.resets, 1);
  delete globalThis.window;
});

test("the idle reset clears the conversation and returns to the start screen", () => {
  const conversation = read("../composables/useAvatarConversation.ts");
  assert.match(conversation, /function resetForNextVisitor\(\): void \{[\s\S]*chat\.disconnect\(\);[\s\S]*chat\.messages\.value = \[\];/);
  assert.match(app, /enabled: \(\) => visitor\.kiosk\.value && started\.value/);
  assert.match(app, /busy: \(\) => avatarResponding\.value/);
  assert.match(app, /resetForNextVisitor\(\);\s*started\.value = false;/);
});

test("typing on a phone shrinks the stage so the keyboard does not push the composer away", () => {
  const panel = read("../components/chat/ChatPanel.vue");
  assert.match(panel, /@focus="handleComposerFocus"/);
  assert.match(panel, /@blur="emit\('composing', false\)"/);
  assert.match(app, /@composing="composing = \$event"/);
  const shell = read("../styles/app-shell.css");
  const mobile = shell.slice(shell.indexOf("@media (max-width: 48rem) {"));
  assert.match(mobile, /\.app-shell\.composing \.stage-card \{\s*height: clamp\(6rem, 20svh, 9rem\);/);
  assert.match(read("../../index.html"), /interactive-widget=resizes-content/);
});

test("kiosk mode comes from the account flag, the device setting, or the URL", () => {
  const mode = read("../composables/useVisitorMode.ts");
  assert.match(mode, /const kiosk = computed\(\(\) => accountKiosk\.value \|\| deviceKiosk\.value\)/);
  assert.match(mode, /localStorage\.setItem\(STORAGE_KEY, "1"\)/);
  assert.match(read("../api/auth.ts"), /kiosk\?: boolean/);
});

test("settings can switch this device into kiosk mode, and staff unlock with the account password", () => {
  const modal = read("../components/controls/SettingsModal.vue");
  assert.match(modal, /切換成展示機台/);
  assert.match(modal, /結束展示機台模式/);
  assert.match(modal, /這個帳號固定是展示機台/);
  assert.match(app, /@enter-kiosk="handleEnterKiosk"/);
  assert.match(app, /visitor\.enterDeviceKiosk\(\);\s*started\.value = false;/);
  assert.match(app, /@unlock-request="showUnlock = true"/);
  assert.match(app, /@unlocked="visitor\.unlock"/);
  const dialog = read("../components/controls/UnlockDialog.vue");
  assert.match(dialog, /await verifyPassword\(password\.value\)/);
  // 密碼錯不能回 401：apiFetch 會把 401 當登入過期，機台就被登出了。
  assert.match(read("../api/auth.ts"), /\/api\/v1\/auth\/verify-password/);
});
