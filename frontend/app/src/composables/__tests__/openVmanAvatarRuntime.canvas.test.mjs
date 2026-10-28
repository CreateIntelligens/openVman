import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(
  new URL("../../../public/js/OpenVmanAvatarRuntime.js", import.meta.url),
  "utf8",
);
// 腳本頂層：建立 video、查 canvas；之後才是 emscripten 的 Module 定義。
const head = source.slice(
  source.indexOf("// 初始化影片播放器"),
  source.indexOf("var Module;"),
);
const callbacks = source.slice(
  source.indexOf("var ASM_CONSTS = {"),
  source.indexOf("function ExitStatus("),
);

function fakeCanvas() {
  const context = {
    clearRect() {}, drawImage() {}, getImageData: () => ({ data: new Uint8ClampedArray(16) }),
    putImageData() {},
  };
  return { isConnected: true, width: 0, height: 0, getContext: () => context, context };
}

function createScope(getCanvas) {
  const scope = vm.createContext({
    console,
    document: {
      createElement: (tag) => ({ tag, style: {}, setAttribute() {}, getContext: () => ({}) }),
      body: { appendChild() {} },
      getElementById: (id) => (id === "canvas_video" ? getCanvas() : null),
    },
  });
  vm.runInContext(head, scope);
  vm.runInContext(callbacks, scope);
  // 頂層 let 不會掛到 vm 的全域物件上，要用表達式取值。
  const read = (expression) => vm.runInContext(expression, scope);
  return { scope, read };
}

test("the runtime script loads even when the stage canvas is not on the page yet", () => {
  let canvas = null;
  const { scope, read } = createScope(() => canvas);
  assert.equal(read("canvas_video"), null);
  assert.equal(read("resolveVideoCanvas()"), false);

  // 沒有 canvas 的那一幀：三個繪圖回呼都要安靜跳過，不能碰 null。
  scope.characterVideo = { readyState: 2, videoWidth: 64, videoHeight: 40, currentTime: 0.2 };
  assert.equal(scope.ASM_CONSTS[2764724](), -1);
  assert.doesNotThrow(() => scope.ASM_CONSTS[2766437](0, 0, 10, 10));
  assert.doesNotThrow(() => scope.ASM_CONSTS[2766941](0, 0, 10, 10));

  // 登入後舞台掛上新的 canvas：下一幀就接上，不用重新載入腳本。
  canvas = fakeCanvas();
  assert.equal(read("resolveVideoCanvas()"), true);
  assert.equal(read("canvas_video"), canvas);
  assert.equal(read("ctx_video"), canvas.context);
});

test("a canvas that left the page is replaced by the one that is mounted now", () => {
  const first = fakeCanvas();
  let current = first;
  const { read } = createScope(() => current);
  assert.equal(read("canvas_video"), first);

  first.isConnected = false;
  const second = fakeCanvas();
  current = second;
  assert.equal(read("resolveVideoCanvas()"), true);
  assert.equal(read("canvas_video"), second);
  assert.equal(read("ctx_video"), second.context);
});
