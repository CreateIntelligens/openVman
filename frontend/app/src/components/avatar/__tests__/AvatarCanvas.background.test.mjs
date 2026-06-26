import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../AvatarCanvas.vue"), "utf8");

test("avatar canvas renders a configurable stage background behind the avatar", () => {
  assert.match(source, /backgroundId\?:\s*AvatarBackgroundId/);
  assert.match(source, /backgroundFit\?:\s*AvatarBackgroundFit/);
  assert.match(source, /customBackgroundUrl\?:\s*string/);
  assert.match(source, /class="avatar-background"/);
  assert.match(source, /:class="backgroundClass"/);
  assert.match(source, /:style="backgroundStyle"/);
  assert.match(source, /avatar-background--clinic/);
  assert.match(source, /avatar-background--studio/);
  assert.match(source, /isUploadedAvatarBackgroundId\(props\.backgroundId\)/);
  assert.match(source, /backgroundImage:\s*`url\(\$\{JSON\.stringify\(url\)\}\)`/);
});

test("custom uploaded backgrounds keep cover sizing instead of tiling small images", () => {
  assert.match(source, /background-repeat:\s*no-repeat/);
  assert.match(source, /background-size:\s*cover/);
  assert.match(source, /\.avatar-background--custom\s*{[^}]*background-color:\s*#0a0a0f;/s);
  assert.doesNotMatch(source, /\.avatar-background--custom\s*{[^}]*\n\s*background:\s*#0a0a0f;/s);
});

test("custom uploaded backgrounds support user-controlled display modes", () => {
  assert.match(source, /function backgroundFitStyle\(fit: AvatarBackgroundFit\)/);
  assert.match(source, /case "repeat":/);
  assert.match(source, /backgroundRepeat:\s*"repeat"/);
  assert.match(source, /backgroundSize:\s*"auto"/);
  assert.match(source, /case "contain":/);
  assert.match(source, /backgroundSize:\s*"contain"/);
  assert.match(source, /backgroundSize:\s*"cover"/);
});
