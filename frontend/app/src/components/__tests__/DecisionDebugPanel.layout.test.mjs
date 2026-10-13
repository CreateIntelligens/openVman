import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const panel = readFileSync(resolve(__dirname, "../debug/DecisionDebugPanel.vue"), "utf8");
const shell = readFileSync(resolve(__dirname, "../../styles/app-shell.css"), "utf8");

function rem(source, selector, property) {
  const block = source.match(new RegExp(`(?:^|\\n)${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`))?.[1];
  assert.ok(block, `missing ${selector}`);
  const value = block.match(new RegExp(`(?:^|[;\\s])${property}:\\s*([\\d.]+)rem`))?.[1];
  assert.ok(value, `${selector} ${property} must be in rem`);
  return Number(value);
}

test("decision debug toggle sits below the quick-question button instead of covering it", () => {
  // 兩顆都釘在舞台右上角：Debug 原本 top 1.5rem，蓋住快速問題圓鈕的上半部（2026-10-12 驗收）。
  const quickTop = rem(shell, ".quick-qa-toggle-btn", "top");
  const quickHeight = rem(shell, ".quick-qa-toggle-btn", "height");
  assert.equal(rem(panel, ".decision-debug", "right"), rem(shell, ".quick-qa-toggle-btn", "right"));
  assert.ok(rem(panel, ".decision-debug", "top") >= quickTop + quickHeight);
  assert.doesNotMatch(panel, /@media[^{]*\{\s*\.decision-debug\s*\{[^}]*top:/, "a breakpoint must not move it back up");
});

test("decision debug panel uses theme tokens and no fixed pixel sizes", () => {
  const style = panel.slice(panel.indexOf("<style"));
  assert.doesNotMatch(style, /#[0-9a-fA-F]{3,8}\b/);
  assert.doesNotMatch(style, /\b(?!1px)\d+px\b/);
});

test("decision debug panel opens as a one-line summary and expands only on request", () => {
  // 整張表一打開就蓋住虛擬人的臉，判讀一到高度又從一行跳成整張（2026-10-13 外部測試回報）。
  assert.match(panel, /const expanded = ref\(false\)/);
  assert.match(panel, /v-if="report && expanded"/);
  assert.match(panel, /prefers-reduced-motion: reduce\) \{ \.debug-details \{ animation: none/);
});
