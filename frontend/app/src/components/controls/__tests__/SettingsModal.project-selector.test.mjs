import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../SettingsModal.vue"), "utf8");

test("settings modal splits brain project selection from persona selection", () => {
  assert.match(source, /export interface ProjectSummary/);
  assert.match(source, /projects:\s*ProjectSummary\[\]/);
  assert.match(source, /currentProjectId:\s*string/);
  assert.match(source, /projectChange:\s*\[projectId:\s*string\]/);
  assert.match(source, /draftProjectId/);
  assert.match(source, />大腦\/知識庫</);
  assert.match(source, />人設</);
  assert.doesNotMatch(source, />大腦人設</);
});

test("project selector is backed by project ids", () => {
  assert.match(source, /v-model="draftProjectId"/);
  assert.match(source, /const projectOptions = computed/);
  assert.match(source, /props\.projects\.map\(\(p\) => \(\{ value: p\.project_id, label: p\.label \|\| p\.project_id \}\)\)/);
  assert.match(source, /:options="projectOptions"/);
});

test("brain project selector is shown before persona selector", () => {
  const projectLabel = source.indexOf(">大腦/知識庫<");
  const personaLabel = source.indexOf(">人設<");

  assert.notEqual(projectLabel, -1, "missing project label");
  assert.notEqual(personaLabel, -1, "missing persona label");
  assert.ok(projectLabel < personaLabel, "project must be selected before persona");
});

test("text chat mode uses a Traditional-Chinese label", () => {
  assert.match(source, /<strong>標準<\/strong>/);
  assert.doesNotMatch(source, /<strong>預設<\/strong>/);
});

test("settings use a native modal dialog with browser-managed focus trapping", () => {
  assert.match(source, /<dialog/);
  assert.match(source, /\.showModal\(\)/);
  assert.match(source, /@cancel\.prevent="close"/);
  assert.match(source, /previouslyFocused\?\.focus\(\)/);
  assert.doesNotMatch(source, /role="dialog"/);
});

test("settings modal exposes stage background controls", () => {
  assert.match(source, /backgroundId:\s*AvatarBackgroundId/);
  assert.match(source, /backgroundUrl:\s*string/);
  assert.match(source, /backgroundFit:\s*AvatarBackgroundFit/);
  assert.match(source, /backgrounds:\s*AvatarBackgroundSummary\[\]/);
  assert.match(source, /backgroundChange:\s*\[\s*backgroundId:\s*AvatarBackgroundId,\s*backgroundUrl:\s*string,\s*backgroundFit:\s*AvatarBackgroundFit,\s*\]/);
  assert.match(source, /draftBackgroundId/);
  assert.match(source, /draftBackgroundUrl/);
  assert.match(source, /draftBackgroundFit/);
  assert.match(source, />背景</);
  assert.match(source, />顯示方式</);
  assert.match(source, /v-for="option in backgroundOptions"/);
  assert.match(source, /v-for="option in backgroundFitOptions"/);
  assert.match(source, /v-model="draftBackgroundId"/);
  assert.match(source, /v-model="draftBackgroundFit"/);
  // 上傳背景的選項由 utils/settingsOptions.ts 組（行為測試在 rootScopeMarking.test.mjs）。
  assert.match(source, /buildBackgroundOptions\(builtInBackgroundOptions, props\.backgrounds\)/);
  assert.match(source, /resolvedDraftBackgroundUrl/);
});

test("character selector lists 2D characters by name and marks VRM avatars", () => {
  assert.match(source, /renderMode:\s*'2d' \| '3d'/);
  assert.match(source, /renderModeChange:\s*\[mode:\s*'2d' \| '3d'\]/);
  assert.match(source, /export interface VrmCharacterSummary/);
  assert.match(source, /vrmCharacters:\s*VrmCharacterSummary\[\]/);
  assert.match(source, /currentVrmId:\s*string/);
  assert.match(source, /vrmCharacterChange:\s*\[vrmId:\s*string\]/);
  assert.match(source, /toOpenVmanCharacterValue/);
  assert.match(source, /toVrmCharacterValue/);
  assert.match(source, /draftCharacterValue/);
  assert.match(source, /v-model="draftCharacterValue"/);
  assert.match(source, /buildCharacterOptions\(props\.characters, props\.vrmCharacters\)/);
  assert.doesNotMatch(source, /openVman 2D/);
  assert.doesNotMatch(source, /· 2D/);
  assert.doesNotMatch(source, /· 3D/);
  assert.doesNotMatch(source, />顯示模式</);
});

test("render mode stays internal to character selection", () => {
  assert.match(source, /draftRenderMode/);
  assert.doesNotMatch(source, /renderModeOptions/);
  assert.doesNotMatch(source, /v-for="option in renderModeOptions"/);
  assert.doesNotMatch(source, /v-model="draftRenderMode"/);
});

test("renderer choice changes remain applyable when renderer controls are disabled", () => {
  assert.match(source, /const isRenderModeDirty = computed/);
  assert.match(source, /const isVrmDirty = computed/);
  assert.match(source, /const rendererChoiceDirty = computed/);
  assert.match(source, /const applyDisabled = computed\(\(\) =>\s*Boolean\(props\.personasLoading\) \|\|\s*\(Boolean\(props\.disabled\) && !rendererChoiceDirty\.value\)\s*\)/);
  assert.match(source, /v-model="draftCharacterValue"/);
});

test("background changes apply without forcing chat reconnect", () => {
  assert.match(source, /const needsReconnect = computed/);
  assert.match(source, /const isBackgroundDirty = computed/);
  assert.match(source, /if \(needsReconnect\.value\) emit\('apply'\)/);
  assert.match(source, /const applyLabel = computed/);
  assert.doesNotMatch(source, /{{ isDirty \? '套用並重新連線' : '關閉' }}/);
});

test("choosing a project applies it so the other menus load that project's lists", () => {
  // 2026-10-16 使用者回報：設定裡換專案，人物、聲音等選單沒跟著換，要關掉重開。
  // 以前換專案只當草稿、只預覽人設；清單都依目前專案載入，所以要立即套用。
  const start = source.indexOf("function handleProjectDraftChange()");
  const body = source.slice(start, source.indexOf("\n}\n", start));
  const emitAt = body.indexOf("emit('projectChange', projectId)");
  assert.notEqual(emitAt, -1, "選了專案要立即送出 projectChange");
  assert.ok(emitAt < body.indexOf("forget("), "先套用專案，再放掉依專案而定的草稿");
  for (const key of ["charId", "ttsProvider", "ttsVoice", "asrProvider", "personaId", "backgroundId"]) {
    assert.match(body, new RegExp(`'${key}'`), `${key} 要改跟新專案的清單`);
  }
  assert.doesNotMatch(source, /projectPreviewChange/);
});
