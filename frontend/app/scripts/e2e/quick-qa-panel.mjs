#!/usr/bin/env node
/**
 * Run against an avatar Vite server: BASE_URL=https://localhost:28887 node
 * scripts/e2e/quick-qa-panel.mjs. Requires the installed agent-browser CLI.
 * Uses fixture QA responses; creates no project data or persistent preferences.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";

const base = new URL(process.env.BASE_URL ?? "https://127.0.0.1:28887");
const session = `quick-qa-regression-${process.pid}`;
const results = [];

function browser(...args) {
  const response = JSON.parse(execFileSync("agent-browser", [
    "--session", session, "--json", "--ignore-https-errors", ...args,
  ], { encoding: "utf8", timeout: 45000, maxBuffer: 2 ** 20 }));
  assert.equal(response.success, true, response.error?.message ?? JSON.stringify(response.error));
  return response.data;
}

const setup = async () => {
  const path = "/src/components/controls/QuickQaPanel.vue";
  const source = await (await fetch(path)).text();
  const vuePath = source.match(/from ["']([^"']*\/vue\.js[^"']*)["']/)?.[1];
  if (!vuePath) throw new Error("Run this regression against the avatar Vite dev server");
  const [{ createApp, h, nextTick, reactive }, { default: QuickQaPanel }] = await Promise.all([
    import(vuePath), import(path),
    import("/src/styles/global.css"), import("/src/styles/app-shell.css"),
  ]);
  document.body.replaceChildren();
  const style = document.createElement("style");
  style.textContent = ".quick-qa-panel { --ov-dur-micro: 0s; transition: none !important; }";
  document.head.append(style);
  const failures = [];
  window.addEventListener("error", (event) => failures.push(event.message));
  window.addEventListener("unhandledrejection", (event) => failures.push(String(event.reason)));
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!url.pathname.startsWith("/api/v1/knowledge/qa/")) return originalFetch(input, init);
    const nodes = [{ node_id: "fixture", label: "Fixture", children: [],
      qa_entries: Array.from({ length: 30 }, (_, i) => ({
        question: `Fixture question ${i + 1}`, source_path: "fixture", hidden: false,
      })),
    }];
    return Promise.resolve(new Response(JSON.stringify(nodes), {
      headers: { "Content-Type": "application/json" },
    }));
  };
  const settle = async () => {
    await nextTick();
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  };
  let app;
  let state;
  window.__quickQaRegression = {
    async mount(immersive, open) {
      app?.unmount();
      document.body.replaceChildren();
      const root = document.createElement("div");
      document.body.append(root);
      state = reactive({ immersive, open });
      // The Teleport target is produced inside this render, just like App.vue.
      // Pre-creating .app-shell in document would conceal the missing-defer bug.
      if (document.querySelector(".app-shell")) throw new Error("Target must not pre-exist mount");
      app = createApp({
        render: () => h("main", { class: ["app-shell", { immersive: state.immersive }] }, [
          h("div", { class: "kiosk-layout" }, [
            h("section", { class: "stage-panel" }, [
              h("div", { class: "stage-card" }, [
                h(QuickQaPanel, { open: state.open, projectId: "fixture", onClose: () => { state.open = false; } }),
              ]),
            ]),
            h("div", { class: "chat-area" }, "Chat stacking-context fixture"),
          ]),
        ]),
      });
      app.config.errorHandler = (error) => failures.push(error.message);
      app.config.warnHandler = (warning) => failures.push(warning);
      app.mount(root);
      await settle();
    },
    async open(value) { state.open = value; await settle(); },
    async inspect() {
      await settle();
      const panel = document.querySelector(".quick-qa-panel");
      if (!panel) return { failures, missing: true };
      const rect = panel.getBoundingClientRect();
      const body = panel.querySelector(".panel-body");
      const button = panel.querySelector(".qa-btn");
      const buttonRect = button?.getBoundingClientRect();
      const hit = buttonRect && document.elementFromPoint(
        buttonRect.x + buttonRect.width / 2, buttonRect.y + buttonRect.height / 2,
      );
      return {
        failures, compact: matchMedia("(max-width: 48rem), (max-height: 36rem)").matches,
        parent: panel.parentElement.className, position: getComputedStyle(panel).position,
        height: rect.height, top: rect.top, bottom: rect.bottom, viewportHeight: innerHeight,
        bodyHeight: body.clientHeight, scrollHeight: body.scrollHeight,
        questionReachable: Boolean(button && (button === hit || button.contains(hit))),
        questionCount: panel.querySelectorAll(".qa-btn").length,
      };
    },
  };
  return true;
};

function inspect(label) {
  const result = browser("eval", "window.__quickQaRegression.inspect()").result;
  assert.deepEqual(result.failures, [], `${label}: Vue/browser errors`);
  assert.equal(result.missing, undefined, `${label}: missing panel`);
  assert.equal(result.parent, result.compact ? "app-shell" + (label.includes("immersive") ? " immersive" : "") : "stage-card",
    `${label}: actual Teleport parent`);
  assert.equal(result.position, result.compact ? "fixed" : "absolute", `${label}: positioning`);
  assert.equal(result.questionCount, 30, `${label}: fixture questions loaded`);
  assert.ok(result.bodyHeight > 40 && result.height > result.bodyHeight, `${label}: usable question viewport`);
  assert.equal(result.questionReachable, true, `${label}: first question hit target`);
  if (result.compact) {
    assert.ok(result.top >= 0 && result.bottom <= result.viewportHeight, `${label}: viewport bounds`);
    assert.ok(result.scrollHeight > result.bodyHeight, `${label}: questions scroll inside panel`);
  }
  results.push({ label, ...result });
}

try {
  // A script document keeps the Vite origin without booting the production App.
  browser("open", new URL("/@vite/client", base).href);
  browser("eval", `(${setup.toString()})()`);
  for (const immersive of [false, true]) {
    const mode = immersive ? "immersive" : "normal";
    for (const [width, height] of [[1440, 900], [320, 667], [375, 667], [414, 896], [768, 1024], [1200, 400]]) {
      browser("set", "viewport", String(width), String(height));
      browser("eval", `window.__quickQaRegression.mount(${immersive}, false)`);
      browser("eval", "window.__quickQaRegression.open(true)");
      inspect(`${mode}-${width}-first-open`);
      browser("eval", "window.__quickQaRegression.open(false)");
      browser("eval", "window.__quickQaRegression.open(true)");
      inspect(`${mode}-${width}-reopen`);
      const nextWidth = width === 375 ? 1440 : 375;
      browser("set", "viewport", String(nextWidth), nextWidth === 375 ? "667" : "900");
      inspect(`${mode}-${width}-resize-${nextWidth}`);
    }
  }
  const pageErrors = browser("errors").errors;
  assert.deepEqual(pageErrors, [], "Uncaught browser errors");
  console.log(JSON.stringify({ passed: true, checks: results.length, pageErrors, results }, null, 2));
} finally {
  browser("close");
}
