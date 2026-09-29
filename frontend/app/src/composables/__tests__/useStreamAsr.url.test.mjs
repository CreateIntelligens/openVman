import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(__dirname, "../../..");
const { outputFiles } = await build({
  stdin: { contents: 'export { streamUrl } from "./src/composables/useStreamAsr";', resolveDir: appRoot, loader: "ts" },
  bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
  alias: {
    "@shared": resolve(appRoot, "../shared"),
    vue: resolve(appRoot, "node_modules/vue/dist/vue.runtime.esm-bundler.js"),
  },
  define: { __VUE_OPTIONS_API__: "true", __VUE_PROD_DEVTOOLS__: "false", "process.env.NODE_ENV": '"production"' },
  external: ["@ricky0123/vad-web"],
});
globalThis.window = { location: { protocol: "https:", host: "146.5gao.ai" } };
const { streamUrl } = await import(`data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`);

test("the stream URL carries the project and its language routes", () => {
  // 後端依專案分流產生 Gemini 語言提示，也拿專案名稱給 Jev 判斷定稿。
  assert.equal(
    streamUrl({ project_id: "proj-0cc5c610b4", language_routes: "zh,en,es" }),
    "wss://146.5gao.ai/api/v1/asr/stream?project_id=proj-0cc5c610b4&language_routes=zh%2Cen%2Ces",
  );
  assert.equal(streamUrl({ project_id: "", language_routes: "" }), "wss://146.5gao.ai/api/v1/asr/stream");
});

test("the app passes the language route fields to the stream", () => {
  const app = readFileSync(resolve(__dirname, "../../App.vue"), "utf8");
  assert.match(app, /useStreamAsr\(\{\s*query: \(\) => languageRoutes\.asrFormFields\(\),/);
});
