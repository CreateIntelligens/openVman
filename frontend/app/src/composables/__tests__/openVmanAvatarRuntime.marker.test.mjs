import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

import ts from "typescript";

const helperSource = readFileSync(
  new URL("../../../../shared/avatar/avatarFrameSyncRepair.ts", import.meta.url), "utf8",
);
const compiled = ts.transpileModule(helperSource, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { installFrameSyncMarkerRepair } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

const source = readFileSync(
  new URL("../../../public/js/OpenVmanAvatarRuntime.js", import.meta.url),
  "utf8",
);
const callbacks = source.slice(
  source.indexOf("var ASM_CONSTS = {"),
  source.indexOf("function ExitStatus("),
);

function backgroundAt(x, y) {
  return [60 + x + y, 90 + x + 2 * y, 120 + x + y, 100 + x + y];
}

function renderFrame({ width = 64, height = 40, markerSize = 8, frame = 0, background = backgroundAt }) {
  const original = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const offset = (y * width + x) * 4;
      original.set(background(x, y), offset);
      if (x >= width - markerSize && y < markerSize) {
        original.set([frame % 7 * 40, frame % 7 * 40, frame % 7 * 40, 255], offset);
      }
    }
  }
  let pixels = original.slice();
  let repairs = 0;
  const context = {
    globalCompositeOperation: "source-over",
    globalAlpha: 0.4,
    clearRect() { pixels.fill(0); },
    drawImage() { pixels = original.slice(); },
    createImageData(width, height) {
      return { width, height, data: new Uint8ClampedArray(width * height * 4) };
    },
    getImageData(x, y, w, h) {
      const data = new Uint8ClampedArray(w * h * 4);
      for (let row = 0; row < h; row++) {
        const offset = ((y + row) * width + x) * 4;
        data.set(pixels.slice(offset, offset + w * 4), row * w * 4);
      }
      return { data, width: w, height: h };
    },
    putImageData(image, x, y) {
      repairs += 1;
      for (let row = 0; row < image.height; row++) {
        pixels.set(
          image.data.subarray(row * image.width * 4, (row + 1) * image.width * 4),
          ((y + row) * width + x) * 4,
        );
      }
    },
  };
  const nativeReader = context.getImageData;
  const canvas = { width, height, getContext: () => context };
  const repair = installFrameSyncMarkerRepair(canvas);
  const scope = vm.createContext({
    canvas_video: canvas,
    characterVideo: {
      readyState: 2, videoWidth: width, videoHeight: height,
      currentTime: (frame + 0.1) / 25,
    },
    ctx_video: context,
    resolveVideoCanvas: () => true,
    console,
  });
  vm.runInContext(callbacks, scope);
  const actualFrame = scope.ASM_CONSTS[2764724]();
  return {
    actualFrame, canvas, context, original, nativeReader, pixels, repair,
    repairs: () => repairs,
    renderAgain: () => scope.ASM_CONSTS[2764724](),
  };
}

test("sync codes survive display repair for small and enlarged markers", () => {
  for (const markerSize of [2, 4, 8, 12]) {
    for (let frame = 0; frame < 14; frame++) {
      const { actualFrame, pixels } = renderFrame({ markerSize, frame });
      assert.equal(actualFrame, frame, `marker=${markerSize}, frame=${frame}`);
      for (let y = 0; y < 16; y++) {
        for (let x = 48; x < 64; x++) {
          assert.deepEqual(
            [...pixels.slice((y * 64 + x) * 4, (y * 64 + x + 1) * 4)],
            backgroundAt(x, y),
          );
        }
      }
    }
  }
});

test("repair preserves all pixels outside the corner and the canvas state", () => {
  const { context, original, pixels } = renderFrame({ frame: 3 });
  for (let y = 0; y < 40; y++) {
    for (let x = 0; x < 64; x++) {
      if (y < 16 && x >= 48) continue;
      const offset = (y * 64 + x) * 4;
      assert.deepEqual(pixels.slice(offset, offset + 4), original.slice(offset, offset + 4));
    }
  }
  assert.equal(context.globalCompositeOperation, "copy");
  assert.equal(context.globalAlpha, 0.4);
});

test("corner repair preserves horizontal and vertical gradients instead of shifting a tile", () => {
  const { pixels } = renderFrame({ frame: 0, markerSize: 8 });
  for (let y = 0; y < 17; y++) {
    for (let x = 47; x < 64; x++) {
      const offset = (y * 64 + x) * 4;
      assert.deepEqual([...pixels.slice(offset, offset + 4)], backgroundAt(x, y));
    }
  }
});

test("feathering preserves the boundary of a curved background", () => {
  const background = (x, y) => [Math.round(40 + x * x / 32 + x * y / 64), 100, 120, 255];
  const { pixels, original } = renderFrame({ background, markerSize: 8 });
  for (let y = 0; y < 16; y++) {
    const offset = (y * 64 + 48) * 4;
    assert.deepEqual(pixels.slice(offset, offset + 4), original.slice(offset, offset + 4));
  }
  for (let x = 48; x < 64; x++) {
    const offset = (15 * 64 + x) * 4;
    assert.deepEqual(pixels.slice(offset, offset + 4), original.slice(offset, offset + 4));
  }
});

test("repair stays inside a small canvas after a character size change", () => {
  const { actualFrame, pixels } = renderFrame({ width: 8, height: 4, markerSize: 2, frame: 5 });
  assert.equal(actualFrame, 5);
  assert.equal(pixels.length, 8 * 4 * 4);
  assert.deepEqual([...pixels.slice(7 * 4, 8 * 4)], backgroundAt(7, 0));
});

test("ordinary pixel reads do not trigger repair and disposal restores the reader", () => {
  const frame = renderFrame({ frame: 4 });
  assert.equal(frame.repairs(), 1);
  frame.context.getImageData(0, 0, 2, 2);
  assert.equal(frame.repairs(), 1);
  frame.repair.restore();
  assert.equal(frame.context.getImageData, frame.nativeReader);
  assert.equal(frame.renderAgain(), 4);
  assert.equal(frame.repairs(), 1);
});

test("disposal does not overwrite a reader subsequently installed by another owner", () => {
  const { context, repair } = renderFrame({});
  const anotherReader = () => {};
  context.getImageData = anotherReader;
  repair.restore();
  assert.equal(context.getImageData, anotherReader);
});
