import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

test("the motion lab ships inside the avatar image instead of a host mount", () => {
  // 預覽放在 public/，Vite 建置時複製進 dist，再由 Dockerfile 打包進 nginx 映像。
  for (const name of ["index.html", "motion-demo.js", "motion-controller.js", "recording-audio.js", "access-check.js", "demo.css", "sample.wav"]) {
    assert.ok(readFileSync(new URL(`../../public/experiments/avatar-motion/${name}`, import.meta.url)).length, `${name} is missing`);
  }
  const viteConfig = readFileSync(new URL("../../vite.config.ts", import.meta.url), "utf8");
  assert.doesNotMatch(viteConfig, /publicDir:\s*false/, "public/ must be copied into the build");

  // 正式 compose 若把主機工作樹掛進 avatar，未提交的修改會直接上線。
  const compose = readFileSync(new URL("../../../../docker-compose.yml", import.meta.url), "utf8");
  const avatar = compose.split("\n  avatar:\n")[1]?.split(/\n  [A-Za-z][\w-]*:\n/)[0];
  assert.ok(avatar, "avatar service is missing");
  assert.doesNotMatch(avatar, /experiments\/avatar-motion/);
});
