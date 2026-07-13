import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcRoot = resolve(__dirname, "../..");

test("frontend wraps the vendor engine behind the openVman runtime name", () => {
  const runtimePath = resolve(srcRoot, "composables/useOpenVmanAvatarRuntime.ts");
  assert.equal(existsSync(runtimePath), true);

  const runtime = readFileSync(runtimePath, "utf-8");
  const app = readFileSync(resolve(srcRoot, "App.vue"), "utf-8");
  const settings = readFileSync(
    resolve(srcRoot, "components/controls/SettingsModal.vue"),
    "utf-8",
  );

  assert.match(runtime, /export function useOpenVmanAvatarRuntime\(\)/);
  assert.match(app, /useOpenVmanAvatarRuntime/);
  assert.doesNotMatch(app, /useMatesX/);
  assert.match(settings, /· openVman 2D/);
  assert.doesNotMatch(settings, /· MatesX/);
});
