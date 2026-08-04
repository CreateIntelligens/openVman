import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const mainSourceUrl = new URL("../src/main.ts", import.meta.url);
const domSourceUrl = new URL("../src/dom.ts", import.meta.url);

test("uses direct light DOM without iframe markup", async () => {
  const source = [
    await readFile(mainSourceUrl, "utf8"),
    await readFile(domSourceUrl, "utf8"),
  ].join("\n");

  assert.doesNotMatch(source, /createElement\(["']iframe["']\)/);
  assert.match(source, /canvas_video/);
  assert.match(source, /canvas_gl/);
  assert.match(source, /openvman-avatar-root/);
});

test("does not use fixed pixel layout dimensions", async () => {
  const source = await readFile(domSourceUrl, "utf8");

  assert.doesNotMatch(source, /(?:width|height|right|bottom):\s*\d+px/);
});

test("keeps contained avatars inside their own positioning context", async () => {
  const source = await readFile(domSourceUrl, "utf8");
  const containedRule = source.match(
    /\.openvman-avatar-root\[data-openvman-contained="true"\]\s*\{([^}]+)\}/,
  );

  assert.ok(containedRule);
  assert.match(containedRule[1], /position:\s*relative/);
  assert.doesNotMatch(containedRule[1], /position:\s*absolute/);
});
