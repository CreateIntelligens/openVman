import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../widget.html"), "utf8");

test("VRM widget auto-fits loaded models from their bounding box", () => {
  assert.match(source, /const VRM_TARGET_HEIGHT = readNumberParam\('vrmTargetHeight', 1\.68, 0\.8, 2\.4\)/);
  assert.match(source, /function fitVRMToCamera\(THREE, vrmScene, camera\)/);
  assert.match(source, /new THREE\.Box3\(\)\.setFromObject\(vrmScene\)/);
  assert.match(source, /if \(!Number\.isFinite\(size\.y\) \|\| size\.y <= 0\) return/);
  assert.match(source, /VRM_TARGET_HEIGHT \/ Math\.max\(size\.y, 0\.001\)/);
  assert.match(source, /camera\.position\.set\(0, center\.y, distance \+ halfDepth\)/);
  assert.match(source, /camera\.lookAt\(center\)/);
  assert.match(source, /if \(fittedVRMScene\) fitVRMToCamera\(THREE, fittedVRMScene, camera\)/);
  assert.match(source, /fitVRMToCamera\(THREE, vrm\.scene, camera\)/);
});
