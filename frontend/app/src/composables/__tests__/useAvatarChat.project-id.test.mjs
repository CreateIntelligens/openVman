import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useAvatarChat.ts"), "utf8");

test("avatar chat keeps project id mutable for settings changes", () => {
  assert.match(source, /let currentProjectId = options\.projectId \?\? ['"]default['"]/);
  assert.match(source, /project_id:\s*currentProjectId/);
  assert.doesNotMatch(source, /const projectId = options\.projectId \?\? ['"]default['"]/);
});

test("avatar chat exposes project and persona setters for reconnect configuration", () => {
  assert.match(source, /function setProject\(projectId: string\): void/);
  assert.match(source, /currentProjectId = projectId/);
  assert.match(source, /function setPersona\(personaId: string\): void/);
  assert.match(source, /currentPersonaId = personaId/);
  assert.match(source, /setProject,/);
  assert.match(source, /setPersona,/);
});
