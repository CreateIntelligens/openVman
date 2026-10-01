import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { build } from "esbuild";
import { compileScript, parse } from "@vue/compiler-sfc";
import { createSSRApp, h } from "vue";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(resolve(appRoot, "package.json"));
const { renderToString } = require("@vue/server-renderer");
const source = readFileSync(resolve(appRoot, "src/App.vue"), "utf8");
const { descriptor } = parse(source);
const compiled = compileScript(descriptor, { id: "thin-entry-regression" });
const { outputFiles } = await build({
  stdin: { contents: compiled.content, resolveDir: resolve(appRoot, "src"), loader: "ts" },
  bundle: true, write: false, platform: "node", format: "esm",
  alias: {
    "@shared": resolve(appRoot, "../shared"),
    vue: resolve(appRoot, "node_modules/vue/dist/vue.runtime.esm-bundler.js"),
  },
  // Rendering children does not exercise domain composition; production build checks their templates.
  plugins: [{ name: "render-only-component-stubs", setup(builder) {
    builder.onResolve({ filter: /\.vue$/ }, (args) => ({ path: args.path, namespace: "children" }));
    builder.onLoad({ filter: /.*/, namespace: "children" }, () => ({ contents: "export default {}", loader: "js" }));
  } }],
  external: ["@ricky0123/vad-web"],
  define: {
    __VUE_OPTIONS_API__: "true", __VUE_PROD_DEVTOOLS__: "false",
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false", "process.env.NODE_ENV": '"production"',
  },
  logLevel: "error",
});

test("the full App setup resolves real catalog and timing callbacks after composition", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const timingPayloads = [];
  globalThis.window = {
    location: { pathname: "/", search: "" }, history: { replaceState() {} },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  };
  globalThis.fetch = async (input, init = {}) => {
    const path = String(input).split("?")[0];
    let body = {};
    if (path.endsWith("/projects")) {
      body = { projects: [{ project_id: "project-fixture", label: "Fixture" }] };
    } else if (path.endsWith("/personas")) {
      body = { personas: [{ persona_id: "default", label: "Default" }] };
    } else if (path.endsWith("/my-asr-provider")) {
      body = { value: "r2t2-live", effective: "r2t2-live", allowed: ["r2t2-live"] };
    } else if (path.endsWith("/metrics/turn")) {
      timingPayloads.push(JSON.parse(init.body));
    }
    return new Response(JSON.stringify(body), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const component = (await import(
      `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`
    )).default;
    let bindings;
    const setup = component.setup;
    component.setup = (props, context) => {
      bindings = setup(props, context);
      return bindings;
    };
    // SSR executes the actual setup with Vue lifecycle context, without opening hardware.
    component.render = () => h("div", "composed");
    assert.equal(await renderToString(createSSRApp(component)), "<div>composed</div>");
    await bindings.bootstrap.fetchInitialProjectData();
    assert.equal(bindings.settings.projectId, "project-fixture");
    assert.equal(bindings.voice.activeAsr.value, bindings.voice.streamAsr);
    bindings.turnTiming.begin();
    bindings.turnTiming.mark("sent");
    bindings.turnTiming.finish("error");
    assert.equal(timingPayloads.length, 1);
    assert.equal(timingPayloads[0].project_id, "project-fixture");
    assert.equal(timingPayloads[0].asr_engine, "r2t2-live");
  } finally {
    globalThis.window = previousWindow;
    globalThis.fetch = previousFetch;
  }
});
