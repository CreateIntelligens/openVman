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
  assert.match(source, /fetch\("\/api\/projects"\)/);
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
