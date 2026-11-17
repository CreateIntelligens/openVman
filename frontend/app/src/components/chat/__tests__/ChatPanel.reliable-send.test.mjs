import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { componentSetup } from "../../../__tests__/helpers/componentSetup.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../ChatPanel.vue"), "utf8");

test("composer clears only after the send callback accepts the draft", () => {
  assert.match(source, /done:\s*\(result:\s*ComposerSendResult\)\s*=>\s*void/);
  assert.match(source, /if \(result\.accepted\)/);
  assert.match(source, /if \(inputText\.value === draft\) inputText\.value = ""/);
  assert.match(source, /內容已保留/);
});

test("composer exposes readiness and ASR errors to assistive technology", () => {
  assert.match(source, /canSend\?:\s*boolean/);
  assert.match(source, /asrSupported\?:\s*boolean/);
  assert.match(source, /role="alert"/);
  assert.match(source, /:aria-describedby=/);
});

for (const event of [
  { isComposing: true, keyCode: 13 },
  { isComposing: false, keyCode: 229 },
]) {
  test(`composition confirmation preserves the draft (isComposing=${event.isComposing}, keyCode=${event.keyCode})`, (t) => {
    const panel = componentSetup(resolve(__dirname, "../ChatPanel.vue"), { messages: [] }, {
      useStickToBottom() {},
    });
    t.after(panel.dispose);
    panel.read('inputText.value = "中文問題"');
    const keyboardEvent = { ...event, preventDefault: () => assert.fail("IME confirmation must keep its default action") };
    panel.read("handleComposerEnter")(keyboardEvent);
    assert.equal(panel.events.length, 0);
    assert.equal(panel.read("inputText.value"), "中文問題");
  });
}

test("a regular Enter submits once and only clears an accepted draft", (t) => {
  const panel = componentSetup(resolve(__dirname, "../ChatPanel.vue"), { messages: [] }, {
    useStickToBottom() {},
  });
  t.after(panel.dispose);
  assert.match(source, /@keydown\.enter="handleComposerEnter"/);
  panel.read('inputText.value = "  中文問題  "');
  let prevented = false;
  panel.read("handleComposerEnter")({
    isComposing: false, keyCode: 13, preventDefault() { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(panel.events.length, 1);
  const [event, text, done] = panel.events[0];
  assert.equal(event, "send");
  assert.equal(text, "中文問題");
  assert.equal(panel.read("inputText.value"), "  中文問題  ");
  done({ accepted: true });
  assert.equal(panel.read("inputText.value"), "");
});
