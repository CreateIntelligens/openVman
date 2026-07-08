import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../App.vue"), "utf8");

test("mascot iframe source is built from the selected mascot", () => {
  assert.match(source, /import MascotSwitcher from "\.\/components\/mascot\/MascotSwitcher\.vue"/);
  assert.match(source, /buildMascotWidgetSrc\(selectedMascot\.value\)/);
  assert.match(source, /:src="mascotWidgetSrc"/);
  assert.match(source, /:key="settings\.mascotId"/);
});

test("mascot switcher can update the selected right-corner assistant", () => {
  assert.match(source, /<MascotSwitcher/);
  assert.match(source, /:mascots="mascotOptions"/);
  assert.match(source, /:current-mascot-id="selectedMascot\.id"/);
  assert.match(source, /@mascot-change="handleMascotChange"/);
  assert.match(source, /function handleMascotChange\(mascotId:\s*string\):\s*void/);
  assert.match(source, /settings\.mascotId = resolveMascotOption\(mascotId,\s*mascotOptions\.value\)\.id/);
});

test("mascot switcher loads the managed mascot catalog", () => {
  assert.match(source, /async function fetchMascots\(\):\s*Promise<void>/);
  assert.match(source, /fetch\("\/api\/avatar\/mascots"\)/);
  assert.match(source, /if \(items\.length > 0\)/);
  assert.match(source, /mascotOptions\.value = items\.map\(toMascotOption\)/);
  assert.match(source, /mascotOptions\.value = \[\.\.\.FALLBACK_MASCOT_CATALOG\]/);
  assert.match(source, /void fetchMascots\(\)/);
});
