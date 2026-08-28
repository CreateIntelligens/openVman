import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../App.vue"), "utf8");

test("settings modal receives project options and emits project changes", () => {
  assert.match(source, /:projects="projects"/);
  assert.match(source, /:current-project-id="settings\.projectId"/);
  assert.match(source, /@project-change="handleProjectChange"/);
});

test("avatar frontend loads personas from the selected project", () => {
  assert.match(source, /apiFetch\("\/api\/projects"\)/);
  assert.match(source, /project_id=\$\{encodeURIComponent\(targetProjectId\)\}/);
  assert.doesNotMatch(source, /\/api\/personas\?project_id=default/);
});

test("chat composable is configured with the selected project and persona before reconnect", () => {
  assert.match(source, /projectId:\s*settings\.projectId/);
  assert.match(source, /chat\.setProject\(settings\.projectId\)/);
  assert.match(source, /chat\.setPersona\(settings\.personaId\)/);
});

test("TTS streamer can inspect available providers for auto streaming", () => {
  assert.match(source, /ttsProviders:\s*\(\) => ttsProviders\.value/);
});

test("camera start resets backend visual event state before capturing frames", () => {
  assert.match(
    source,
    /await chat\.resetVisualInput\(\)[\s\S]*?await webcam\.start\(\)/,
  );
  assert.match(source, /:visual-state="chat\.visualState\.value"/);
});

test("avatar stage background is wired through settings", () => {
  assert.match(source, /:background-id="settings\.backgroundId"/);
  assert.match(source, /:custom-background-url="settings\.backgroundUrl"/);
  assert.match(source, /:background-fit="settings\.backgroundFit"/);
  assert.match(source, /:backgrounds="backgrounds"/);
  assert.match(source, /:background-url="settings\.backgroundUrl"/);
  assert.match(source, /@background-change="handleBackgroundChange"/);
  assert.match(source, /function handleBackgroundChange\(\s*backgroundId:\s*AvatarBackgroundId,\s*backgroundUrl:\s*string,\s*backgroundFit:\s*AvatarBackgroundFit,\s*\):\s*void/);
  assert.match(source, /settings\.backgroundId = backgroundId/);
  assert.match(source, /settings\.backgroundUrl = backgroundUrl/);
  assert.match(source, /settings\.backgroundFit = backgroundFit/);
});

test("avatar frontend loads uploaded backgrounds for settings", () => {
  assert.match(source, /apiFetch\("\/api\/backgrounds"\)/);
  assert.match(source, /const items = data\.backgrounds \?\? \[\]/);
  assert.match(source, /backgrounds\.value = items/);
  assert.match(source, /void fetchBackgrounds\(\)/);
});
