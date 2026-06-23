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
  assert.match(source, /v-for="p in projects"/);
  assert.match(source, /:key="p\.project_id"/);
  assert.match(source, /:value="p\.project_id"/);
});

test("brain project selector is shown before persona selector", () => {
  const projectLabel = source.indexOf(">大腦/知識庫<");
  const personaLabel = source.indexOf(">人設<");

  assert.notEqual(projectLabel, -1, "missing project label");
  assert.notEqual(personaLabel, -1, "missing persona label");
  assert.ok(projectLabel < personaLabel, "project must be selected before persona");
});

test("text chat mode keeps the Standard label", () => {
  assert.match(source, /<strong>Standard<\/strong>/);
  assert.doesNotMatch(source, /<strong>預設<\/strong>/);
});
