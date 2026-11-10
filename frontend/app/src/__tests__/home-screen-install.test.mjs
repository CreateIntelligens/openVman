import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const html = readFileSync(resolve(appRoot, "index.html"), "utf8");
const manifest = JSON.parse(
  readFileSync(resolve(appRoot, "public/manifest.webmanifest"), "utf8"),
);

function pngSize(publicPath) {
  const file = readFileSync(resolve(appRoot, "public", publicPath.slice(1)));
  return `${file.readUInt32BE(16)}x${file.readUInt32BE(20)}`;
}

test("iPhone opens the home-screen app without browser bars", () => {
  assert.match(html, /name="apple-mobile-web-app-capable" content="yes"/);
  assert.match(html, /rel="manifest" href="\/manifest\.webmanifest"/);
  assert.equal(manifest.display, "standalone");
});

test("the home-screen app reopens the address it was added from", () => {
  assert.equal(manifest.start_url, undefined);
  assert.equal(manifest.scope, "/");
});

test("status bar stays opaque so content is not drawn under the notch", () => {
  assert.match(html, /apple-mobile-web-app-status-bar-style" content="black"/);
  assert.doesNotMatch(html, /viewport-fit=cover/);
});

test("every declared icon exists at its declared size", () => {
  const touchIcon = html.match(/rel="apple-touch-icon" href="([^"]+)"/)?.[1];
  assert.ok(touchIcon, "missing apple-touch-icon");
  assert.equal(pngSize(touchIcon), "180x180");
  for (const icon of manifest.icons) {
    assert.ok(existsSync(resolve(appRoot, "public", icon.src.slice(1))));
    assert.equal(pngSize(icon.src), icon.sizes);
  }
});
