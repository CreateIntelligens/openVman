import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../widget.html"), "utf8");

test("VRM widget exposes semantic gesture names for OpenVman states", () => {
  assert.match(source, /const VRMA_GESTURES = \{/);
  assert.match(source, /'wave-soft': TK \+ 'Goodbye\.vrma'/);
  assert.match(source, /'thinking-hand': TK \+ 'Thinking\.vrma'/);
  assert.match(source, /'look-around': TK \+ 'LookAround\.vrma'/);
  assert.match(source, /'relax-shift': TK \+ 'Relax\.vrma'/);
  assert.match(source, /'bow-light': 'https:\/\/cdn\.jsdelivr\.net\/gh\/hirokazuniimoto\/virtual-avatar-sdk@main\/assets\/animations\/quick_formal_bow\.vrma'/);
});

test("VRM widget has procedural fallbacks for missing short gestures", () => {
  assert.match(source, /const PROCEDURAL_GESTURES = \{/);
  assert.match(source, /'nod-small': \{ duration: 0\.9 \}/);
  assert.match(source, /'explain-open-hand': \{ duration: 1\.6 \}/);
  assert.match(source, /function startProceduralGesture\(name\)/);
  assert.match(source, /function proceduralGesturePose\(dt\)/);
});

test("VRM widget uses semantic gesture groups without touching mouth tracks", () => {
  assert.match(source, /const TAP_GESTURES = \['wave-soft', 'bow-light', 'nod-small'\]/);
  assert.match(source, /const IDLE_GESTURES = \['look-around', 'relax-shift'\]/);
  assert.ok(source.includes("const bodyOnly = (cl) => { cl.tracks = cl.tracks.filter((tr) => /\\.quaternion$/.test(tr.name)); return cl; }"));
  assert.match(source, /playGesture\(IDLE_GESTURES\[Math\.floor\(Math\.random\(\) \* IDLE_GESTURES\.length\)\]\)/);
});

test("VRM widget accepts host-triggered semantic gestures", () => {
  assert.match(source, /if \(d\.type === 'gesture' && typeof d\.name === 'string'\) gesture3D && gesture3D\(d\.name\)/);
  assert.match(source, /gesture3D = playGesture/);
});
