import { readAppComposition, readAppModule } from "./helpers/appSources.mjs";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 前台以前有 chat.interrupt() 卻沒接到任何按鈕，只能等虛擬人講完（2026-09-29）。
const __dirname = dirname(fileURLToPath(import.meta.url));
const app = readAppComposition("useAvatarConversation", "useImmersiveView");
const panel = readFileSync(resolve(__dirname, "../components/chat/ChatPanel.vue"), "utf8");

test("the composer turns into a stop button while the avatar is answering", () => {
  assert.match(panel, /v-if="responding && !inputText\.trim\(\)"[\s\S]*?@click="emit\('stop'\)"/);
  assert.match(app, /:responding="avatarResponding"/);
  assert.match(app, /@stop="handleStopResponse"/);
  assert.match(app, /function handleStopResponse\(\): void \{\s*chat\.interrupt\(\);/);
});

test("standard mode still counts as answering while audio plays", () => {
  // 標準模式回覆一到 state 就回 IDLE，只看 state 會讓停止鈕在講話時消失。
  const block = app.match(/const avatarResponding = computed\(\(\) =>([\s\S]*?)\);/);
  assert.ok(block);
  assert.match(block[1], /audio\.isPlaying\.value/);
  assert.match(block[1], /isTyping\.value/);
});

test("Escape stops the answer before leaving immersive mode", () => {
  const stop = app.indexOf("} else if (avatarResponding.value) {");
  const immersive = app.indexOf("} else if (immersive.value || document.fullscreenElement) {");
  assert.ok(stop > 0 && immersive > stop);
});
