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
  const app = readFileSync(resolve(srcRoot, "App.vue"), "utf-8") + "\n" + readFileSync(resolve(srcRoot, "composables/useAvatarStage.ts"), "utf8");
  const settings = readFileSync(
    resolve(srcRoot, "components/controls/SettingsModal.vue"),
    "utf-8",
  );

  assert.match(runtime, /export function useOpenVmanAvatarRuntime\(\)/);
  assert.match(app, /useOpenVmanAvatarRuntime/);
  assert.doesNotMatch(app, /useMatesX/);
  assert.doesNotMatch(settings, /· MatesX/);
});

test("avatar runtime loads the engine from the same origin", () => {
  const runtime = readFileSync(resolve(srcRoot, "../public/js/OpenVmanAvatarRuntime.js"), "utf-8");
  assert.deepEqual(runtime.match(/https?:\/\/[^\s"'`]+/g) ?? [], []);
});

test("engine wasm ships under the openVman runtime name", () => {
  const publicRoot = resolve(srcRoot, "../public");
  assert.equal(existsSync(resolve(publicRoot, "wasm/OpenVmanAvatarRuntime.wasm")), true);
  assert.equal(existsSync(resolve(publicRoot, "wasm/DHLiveMini2.wasm")), false);

  const runtime = readFileSync(resolve(publicRoot, "js/OpenVmanAvatarRuntime.js"), "utf-8");
  const adapter = readFileSync(resolve(srcRoot, "composables/useOpenVmanAvatarRuntime.ts"), "utf-8");
  for (const source of [runtime, adapter]) {
    assert.match(source, /wasm\/OpenVmanAvatarRuntime\.wasm/);
    assert.doesNotMatch(source, /DHLiveMini/);
  }
});

test("runtime comments and prompts use Traditional Chinese", () => {
  const runtime = readFileSync(resolve(srcRoot, "../public/js/OpenVmanAvatarRuntime.js"), "utf-8");
  // 只列這支檔案曾出現過的簡體字，不是完整的簡繁對照。
  const simplified = /[获频画检统于选择执后续将挂载还页录帧脚绘过个视]/g;
  assert.deepEqual(runtime.match(simplified) ?? [], []);
});
