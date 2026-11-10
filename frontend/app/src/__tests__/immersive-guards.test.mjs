import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

async function load(relativePath) {
  const { outputText } = ts.transpileModule(
    readFileSync(resolve(sourceRoot, relativePath), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } },
  );
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

const { installImmersiveGuards } = await load("utils/immersiveGuards.ts");
const {
  currentFullscreenElement,
  enterFullscreen,
  exitFullscreen,
  fullscreenChangeEvent,
} = await load("sessionCleanup.ts");

function fire(root, name, target) {
  const event = new Event(name, { cancelable: true });
  if (target) Object.defineProperty(event, "target", { value: target });
  root.dispatchEvent(event);
  return event.defaultPrevented;
}

const plain = { closest: () => null };
const input = { closest: () => ({}) };

for (const name of ["contextmenu", "dragstart", "gesturestart"]) {
  test(`${name} is blocked only while immersive`, () => {
    const root = new EventTarget();
    let immersive = false;
    const remove = installImmersiveGuards(() => immersive, root);
    assert.equal(fire(root, name, plain), false);
    immersive = true;
    assert.equal(fire(root, name, plain), true);
    remove();
    assert.equal(fire(root, name, plain), false);
  });
}

test("inputs keep their long-press menu while immersive", () => {
  const root = new EventTarget();
  installImmersiveGuards(() => true, root);
  assert.equal(fire(root, "contextmenu", input), false);
});

test("immersive stylesheet keeps inputs selectable", () => {
  const css = readFileSync(resolve(sourceRoot, "styles/global.css"), "utf8");
  assert.match(css, /html:has\(\.app-shell\.immersive\) \{[^}]*user-select: none;/);
  assert.match(css, /:is\(input, textarea, \[contenteditable\]\) \{[^}]*user-select: text;/);
});

test("the prefixed API is used when the standard one is missing", async () => {
  const calls = [];
  await enterFullscreen({ webkitRequestFullscreen: () => calls.push("enter") });
  await exitFullscreen({ webkitExitFullscreen: () => calls.push("exit") });
  assert.deepEqual(calls, ["enter", "exit"]);
  const element = {};
  assert.equal(currentFullscreenElement({ webkitFullscreenElement: element }), element);
});

test("the standard API wins when both exist", async () => {
  const calls = [];
  await enterFullscreen({
    requestFullscreen: async () => calls.push("standard"),
    webkitRequestFullscreen: () => calls.push("prefixed"),
  });
  assert.deepEqual(calls, ["standard"]);
});

test("a device with no fullscreen API reports failure so the caller can stay immersive", async () => {
  await assert.rejects(enterFullscreen({}));
});

test("only one fullscreen change event is subscribed", () => {
  assert.equal(fullscreenChangeEvent({ onfullscreenchange: null }), "fullscreenchange");
  assert.equal(fullscreenChangeEvent({}), "webkitfullscreenchange");
});

test("the toolbar stays visible while it carries an error message", () => {
  const app = readFileSync(resolve(sourceRoot, "App.vue"), "utf8");
  assert.match(
    app,
    /controlsHidden = computed\(\(\) => immersive\.value && !controlsRevealed\.value && !rendererErrorMessage\.value\)/,
  );
});

test("a hidden toolbar cannot be tapped by accident", () => {
  const css = readFileSync(resolve(sourceRoot, "styles/app-shell.css"), "utf8");
  assert.match(css, /\.controls-hidden \.control-area \{[^}]*pointer-events: none;/);
});
