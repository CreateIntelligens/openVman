import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const root = read("../Root.vue");
const controlBar = read("../components/controls/ControlBar.vue");

test("the account and logout live in the control bar, not in a bar of their own", () => {
  assert.doesNotMatch(root, /session-toolbar/);
  assert.match(controlBar, /<SessionLabel v-if="settingsVisible !== false" \/>/);
  assert.match(controlBar, /v-if="settingsVisible !== false"\s+class="control-btn control-btn--logout"/);
  assert.match(controlBar, /@click="handleLogout"/);
  // 登出排在按鈕列最後。
  assert.ok(controlBar.indexOf("control-btn--logout") > controlBar.indexOf("toggleImmersive"));
});

test("the title keeps room instead of being squeezed out by the buttons", () => {
  assert.match(controlBar, /\.control-bar__left \{\s*flex: 1 1 10rem;/);
});

test("no stylesheet still reserves room for the old floating account bar", () => {
  assert.doesNotMatch(read("../styles/app-shell.css"), /session-toolbar/);
});

test("logging out from the forbidden page and the control bar share one flow", () => {
  assert.match(root, /useSessionLogout\(\)/);
  assert.match(controlBar, /useSessionLogout\(\)/);
});
