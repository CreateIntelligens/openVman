import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../App.vue"), "utf8");
const bridgeSource = readFileSync(
  resolve(__dirname, "../composables/useStageAvatarBridge.ts"), "utf8",
);

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
  assert.match(source, /const mascot = selectedVrmAvatar\.value/);
  assert.match(source, /buildMascotWidgetSrc\(mascot\)/);
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
  assert.match(source, /apiFetch\("\/api\/v1\/avatar\/mascots"\)/);
  assert.match(source, /toMascotOption/);
  assert.match(source, /\.filter\(\(mascot\) => mascot\.engine === "3d" && Boolean\(mascot\.vrmUrl\)\)/);
});

test("audio mouth movement targets the active 3D stage renderer", () => {
  // 嘴型與手勢的實作搬到 useStageAvatarBridge，這裡只確認 App.vue 有接上它，
  // 以及舊的 mascot 版本沒有殘留。函式怎麼宣告是實作細節，不該綁死在測試裡。
  assert.match(source, /useStageAvatarBridge\(/);
  assert.match(source, /driveMouth:\s*driveStageAvatarMouth/);
  assert.match(source, /stopMouth:\s*stopStageAvatarMouth/);
  assert.match(source, /onPlaybackVolume:\s*driveStageAvatarMouth/);
  assert.doesNotMatch(source, /driveMascotMouth/);
  assert.doesNotMatch(source, /stopMascotMouth/);
});

test("the stage bridge only drives the 3D renderer", () => {
  // 2D 模式沒有可驅動的模型，送過去只會被忽略；這個判斷現在住在 composable。
  assert.match(bridgeSource, /renderMode\(\) !== '3d'/);
  assert.match(bridgeSource, /type: 'mouth', volume/);
  assert.match(bridgeSource, /type: 'gesture', name/);
});

test("chat states trigger semantic VRM stage gestures", () => {
  assert.match(source, /triggerGesture:\s*triggerStageAvatarGesture/);
  assert.match(source, /if \(newState === 'THINKING'\) triggerStageAvatarGesture\("thinking-hand"\)/);
  assert.match(source, /if \(newState === 'SPEAKING'\) triggerStageAvatarGesture\("explain-open-hand"\)/);
});
