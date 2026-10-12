import { loadAvatarChat } from './helpers/avatarChatModule.mjs';
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const appSource = readFileSync(resolve(__dirname, "../../App.vue"), "utf8") + "\n" + readFileSync(resolve(__dirname, "..//useAvatarConversation.ts"), "utf8");
const { useAvatarChat } = await loadAvatarChat(
  "const apiFetch = (url, init) => fetch(url, { ...init, credentials: 'include' });",
);

async function waitForMicrotasks() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("text-mode user input stops current speech and aborts the previous request", async () => {
  const previousFetch = globalThis.fetch;
  const requests = [];
  let stopAudioCount = 0;

  globalThis.fetch = async (_url, init) => {
    requests.push(init);
    return new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
  };

  try {
    const chat = useAvatarChat({
      mode: "text",
      chatEndpoint: "/chat",
      onStopAudio: () => {
        stopAudioCount += 1;
      },
    });

    await chat.connect();
    chat.sendMessage("第一句");
    await waitForMicrotasks();
    const firstSignal = requests[0].signal;
    assert.equal(stopAudioCount, 0);

    chat.sendMessage("第二句");
    await waitForMicrotasks();

    assert.equal(stopAudioCount, 1);
    assert.equal(firstSignal.aborted, true);
    assert.equal(requests.length, 2);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("avatar shell flushes scheduled audio when speech is interrupted", () => {
  assert.match(
    appSource,
    /onStopAudio:\s*\(\)\s*=>\s*\{[\s\S]*audio\.flush\(\)[\s\S]*wasm\.clearAudio\(\)/,
  );
});
