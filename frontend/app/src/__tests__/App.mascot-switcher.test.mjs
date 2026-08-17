import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../App.vue"), "utf8");

test("app no longer mounts the right-corner mascot widget", () => {
  assert.doesNotMatch(source, /class="mascot-widget"/);
  assert.doesNotMatch(source, /class="mascot-reopen-button"/);
  assert.doesNotMatch(source, /<MascotSwitcher/);
});

test("VRM mode renders the selected avatar widget inside the main stage", () => {
  assert.match(source, /settings\.renderMode === ['"]3d['"]/);
  assert.match(source, /class="stage-avatar-frame"/);
  assert.match(source, /ref="stageAvatarFrameRef"/);
  assert.match(source, /:src="stageAvatarWidgetSrc"/);
  assert.match(source, /buildMascotWidgetSrc\(selectedVrmAvatar\.value\)/);
  assert.match(source, /:vrm-characters="vrmCharacterOptions"/);
  assert.match(source, /@vrm-character-change="handleVrmAvatarChange"/);
  assert.doesNotMatch(source, /THREE_D_AVATAR_OPTION/);
});

test("main stage background is shared behind the VRM renderer", () => {
  assert.match(source, /class="stage-background"/);
  assert.match(source, /:class="stageBackgroundClass"/);
  assert.match(source, /:style="stageBackgroundStyle"/);
  assert.match(source, /const stageBackgroundClass = computed/);
  assert.match(source, /const stageBackgroundStyle = computed/);
  assert.match(source, /isUploadedAvatarBackgroundId/);
});

test("VRM choices are loaded from the avatar mascot catalog", () => {
  assert.match(source, /async function fetchVrmAvatars\(\):\s*Promise<void>/);
  assert.match(source, /apiFetch\("\/api\/avatar\/mascots"\)/);
  assert.match(source, /toMascotOption/);
  assert.match(source, /\.filter\(\(mascot\) => mascot\.engine === "3d" && Boolean\(mascot\.vrmUrl\)\)/);
});

test("audio mouth movement targets the active 3D stage renderer", () => {
  assert.match(source, /function driveStageAvatarMouth\(volume:\s*number\):\s*void/);
  assert.match(source, /function stopStageAvatarMouth\(\):\s*void/);
  assert.match(source, /onPlaybackVolume:\s*driveStageAvatarMouth/);
  assert.doesNotMatch(source, /driveMascotMouth/);
  assert.doesNotMatch(source, /stopMascotMouth/);
});

test("chat states trigger semantic VRM stage gestures", () => {
  assert.match(source, /function triggerStageAvatarGesture\(name:\s*string\):\s*void/);
  assert.match(source, /postToStageAvatar\(\{ type: "gesture", name \}\)/);
  assert.match(source, /if \(newState === 'THINKING'\) triggerStageAvatarGesture\("thinking-hand"\)/);
  assert.match(source, /if \(newState === 'SPEAKING'\) triggerStageAvatarGesture\("explain-open-hand"\)/);
});
