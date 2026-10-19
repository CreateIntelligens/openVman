import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

import ts from "typescript";

// 兩個 shared 模組互相 import，先轉譯再用 data URL 串起來。
function transpile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  return ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
}
const repairUrl = `data:text/javascript;base64,${Buffer.from(
  transpile("../../../../shared/avatar/avatarFrameSyncRepair.ts"),
).toString("base64")}`;
const clockSource = transpile("../../../../shared/avatar/avatarFrameClock.ts")
  .replace('"./avatarFrameSyncRepair"', JSON.stringify(repairUrl));
const { installFrameClock } = await import(
  `data:text/javascript;base64,${Buffer.from(clockSource).toString("base64")}`
);

const source = readFileSync(
  new URL("../../../public/js/OpenVmanAvatarRuntime.js", import.meta.url),
  "utf8",
);
const callbacks = source.slice(
  source.indexOf("var ASM_CONSTS = {"),
  source.indexOf("function ExitStatus("),
);

const WIDTH = 64;
const HEIGHT = 40;

function fakeVideo({ withCallback = true } = {}) {
  const pending = [];
  const video = {
    readyState: 2, videoWidth: WIDTH, videoHeight: HEIGHT, currentTime: 0, currentSrc: "a.webm",
    cancelled: [],
  };
  if (withCallback) {
    video.requestVideoFrameCallback = (callback) => {
      pending.push(callback);
      return pending.length;
    };
    video.cancelVideoFrameCallback = (handle) => video.cancelled.push(handle);
  }
  // 模擬瀏覽器送出一幀：把登記的回呼拿出來叫，回呼會再登記下一次。
  video.present = (mediaTime) => {
    const callback = pending.shift();
    callback(0, { mediaTime });
  };
  return video;
}

function fakeCanvas(video) {
  const calls = [];
  const context = {
    globalCompositeOperation: "source-over",
    clearRect() { calls.push("clearRect"); },
    drawImage(...args) { calls.push(args[0] === video ? "drawVideo" : "drawOther"); },
    getImageData(x, y, w, h) {
      calls.push(`read ${w}x${h}`);
      // 角標路徑：畫面右上角是 (frame % 7) * 40 的灰階。
      const marker = (Math.floor(video.currentTime * 25) % 7) * 40;
      const data = new Uint8ClampedArray(w * h * 4).fill(marker);
      for (let i = 3; i < data.length; i += 4) data[i] = 255;
      return { width: w, height: h, data };
    },
    createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
    putImageData() { calls.push("repair"); },
  };
  const canvas = { width: WIDTH, height: HEIGHT, getContext: () => context };
  return { canvas, context, calls };
}

function runtimeScope(video, canvas, context, windowObject) {
  const scope = vm.createContext({
    canvas_video: canvas, characterVideo: video, ctx_video: context,
    resolveVideoCanvas: () => true, window: windowObject, console,
  });
  vm.runInContext(callbacks, scope);
  return () => scope.ASM_CONSTS[2764724]();
}

test("the runtime takes the frame from rVFC and skips the marker read", () => {
  const video = fakeVideo();
  const { canvas, context, calls } = fakeCanvas(video);
  const windowObject = { characterVideo: video };
  globalThis.window = windowObject;
  try {
    const clock = installFrameClock(video, canvas);
    assert.ok(clock);
    const render = runtimeScope(video, canvas, context, windowObject);

    // 還沒有任何一幀被畫出來：退回角標路徑。
    video.currentTime = 7 / 25;
    assert.equal(render(), 7);
    assert.ok(calls.includes("read 2x2"));
    calls.length = 0;

    // 第 12 幀上畫面（currentTime 落後一幀也沒關係）。
    video.present(12 / 25);
    video.currentTime = 11 / 25;
    assert.equal(render(), 12);
    // 角落修補自己要取 17x17 樣本，但 2x2 的角標讀取不該再出現。
    assert.deepEqual(calls, ["clearRect", "drawVideo", "read 17x17", "repair"]);

    // 換角色：舊的 mediaTime 不算數，直到新片的第一幀出來。
    video.currentSrc = "b.webm";
    calls.length = 0;
    video.currentTime = 3 / 25;
    assert.equal(render(), 3);
    assert.ok(calls.includes("read 2x2"));
    video.present(0);
    assert.equal(render(), 0);

    clock.restore();
    assert.equal(video.cancelled.length, 1);
    assert.equal(windowObject.openVmanFrameClock, undefined);
    calls.length = 0;
    context.drawImage(video, 0, 0, WIDTH, HEIGHT);
    assert.deepEqual(calls, ["drawVideo"]);
  } finally {
    delete globalThis.window;
  }
});

test("without requestVideoFrameCallback nothing is installed and the marker path stays", () => {
  const video = fakeVideo({ withCallback: false });
  const { canvas, context, calls } = fakeCanvas(video);
  const windowObject = { characterVideo: video };
  globalThis.window = windowObject;
  try {
    assert.equal(installFrameClock(video, canvas), null);
    const render = runtimeScope(video, canvas, context, windowObject);
    video.currentTime = 5 / 25;
    assert.equal(render(), 5);
    assert.ok(calls.includes("read 2x2"));
  } finally {
    delete globalThis.window;
  }
});
