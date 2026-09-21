import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../App.vue"), "utf8");

const healthFn = source.slice(
  source.indexOf("async function fetchVisionHealth"),
  source.indexOf("async function handleToggleCamera"),
);

test("an unauthorized health check does not count as vision being available", () => {
  // 開場的請求偶爾跑在 cookie 生效前面，後端回 401。把它當成 fail-open 會讓
  // 沒開 VLM 的環境冒出鏡頭按鈕——實際發生過。
  assert.match(healthFn, /res\.status === 401 \|\| res\.status === 403/);

  // 401 分支要在泛用的 !res.ok fail-open 之前，否則永遠走不到。
  assert.ok(
    healthFn.indexOf("res.status === 401") < healthFn.indexOf("if (!res.ok)"),
    "401 的判斷要排在 !res.ok 的 fail-open 前面",
  );
});

test("a still-unauthorized retry leaves the camera hidden instead of guessing", () => {
  // 重問一次仍是 401 就維持 null（不顯示）。猜「可用」會讓按鈕又冒出來，
  // 猜「不可用」則會在後端真的掛掉時把功能藏起來。
  assert.match(healthFn, /fetchVisionHealth\(false\)/);
  const unauthorizedBranch = healthFn.slice(
    healthFn.indexOf("res.status === 401"),
    healthFn.indexOf("if (!res.ok)"),
  );
  assert.doesNotMatch(unauthorizedBranch, /visionAvailable\.value = true/);
});

test("other failures still fail open so a flaky backend does not hide the feature", () => {
  assert.match(healthFn, /if \(!res\.ok\) \{[\s\S]{0,200}visionAvailable\.value = true/);
});

test("the camera button is hidden rather than disabled when vision is off", () => {
  // disabled 的按鈕仍然看得到，使用者會一直問「為什麼點不了」。
  assert.match(source, /:camera-available="visionAvailable === true"/);
  const controlBar = readFileSync(
    resolve(__dirname, "../components/controls/ControlBar.vue"),
    "utf8",
  );
  assert.match(controlBar, /v-if="cameraAvailable"/);
});
