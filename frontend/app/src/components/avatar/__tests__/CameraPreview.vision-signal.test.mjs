import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../CameraPreview.vue"), "utf8");

test("camera preview renders the visual signal inside the camera frame", () => {
  assert.match(source, /visualState:\s*VisualState/);
  assert.match(source, /camera-preview__signal/);
  assert.match(source, /camera-preview__signal--\$\{visualState\.color\}/);
  assert.match(source, /{{ visualState\.label }}/);
  assert.match(source, /right:\s*0\.375rem/);
});
