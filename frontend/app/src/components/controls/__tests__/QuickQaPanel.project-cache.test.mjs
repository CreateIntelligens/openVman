import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import { nextTick } from "vue";
import { componentSetup } from "../../../__tests__/helpers/componentSetup.mjs";

const panelPath = new URL("../QuickQaPanel.vue", import.meta.url);
const helperSource = readFileSync(new URL("../quickQaText.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(helperSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext },
});
const copyHelpers = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);
const flush = () => new Promise((resolve) => setImmediate(resolve));
const node = (project) => ({
  node_id: `${project}-node`, label: project, children: [],
  qa_entries: [{ question: "Shared question", source_path: project, hidden: false }],
});

function createPanel(t) {
  const requests = [];
  const viewport = { matches: false, addEventListener() {}, removeEventListener() {} };
  const panel = componentSetup(panelPath, { open: false, projectId: "A" }, {
    ...copyHelpers,
    window: { matchMedia: () => viewport },
    apiFetch: (url) => new Promise((resolve, reject) => requests.push({
      url, reject, resolve: (data) => resolve({ ok: true, json: async () => data }),
    })),
  });
  panel.mount();
  t.after(panel.dispose);
  return { panel, requests, viewport };
}

async function openAndLoad(panel, requests, project) {
  panel.props.open = true;
  await nextTick();
  requests.at(-1).resolve([node(project)]);
  await flush();
}

test("closed project changes clear both question and merged-answer caches before reopening", async (t) => {
  const { panel, requests } = createPanel(t);
  await openAndLoad(panel, requests, "A");
  panel.read("enterNode(nodes.value[0])");
  await nextTick();
  requests.at(-1).resolve([{ q: "Shared question", a: "Answer A" }]);
  await flush();
  assert.equal(panel.read('mergedQaCache.value["Shared question"].a'), "Answer A");

  panel.props.open = false;
  await nextTick();
  panel.props.projectId = "B";
  assert.equal(panel.read("nodes.value.length"), 0);
  assert.equal(panel.read("currentPath.value.length"), 0);
  assert.equal(panel.read("Object.keys(mergedQaCache.value).length"), 0);
  assert.equal(requests.length, 2, "a closed panel waits to fetch B");

  await openAndLoad(panel, requests, "B");
  assert.match(requests.at(-1).url, /project_id=B$/);
  assert.equal(panel.read("currentQuestions.value[0].source_path"), "B");
  panel.read('selectQuestion("Shared question", "B")');
  const selection = panel.events.find(([event]) => event === "select-question");
  assert.equal(selection[3], "", "B cannot receive A's cached answer for the same question");
});

test("out-of-order node responses cannot replace the selected project's questions", async (t) => {
  const { panel, requests } = createPanel(t);
  panel.props.open = true;
  await nextTick();
  const oldRequest = requests[0];
  panel.props.projectId = "B";
  requests.at(-1).resolve([node("B")]);
  await flush();
  oldRequest.resolve([node("A")]);
  await flush();
  assert.equal(panel.read("nodes.value[0].node_id"), "B-node");
  assert.equal(panel.read("error.value"), null);
  assert.equal(panel.read("loading.value"), false);
});

test("an old request stays invalid after switching A to B and back to A", async (t) => {
  const { panel, requests } = createPanel(t);
  panel.props.open = true;
  await nextTick();
  const oldRequest = requests[0];
  panel.props.projectId = "B";
  panel.props.projectId = "A";
  oldRequest.resolve([node("obsolete-A")]);
  await flush();
  assert.equal(panel.read("nodes.value.length"), 0);
  assert.equal(panel.read("loading.value"), true, "old finally must not hide the new request's loading state");
  requests.at(-1).resolve([node("fresh-A")]);
  await flush();
  assert.equal(panel.read("nodes.value[0].node_id"), "fresh-A-node");
});

test("a rejected old request does not expose its error or finish the new project's loading state", async (t) => {
  const { panel, requests } = createPanel(t);
  panel.props.open = true;
  await nextTick();
  const oldRequest = requests[0];
  panel.props.projectId = "B";
  oldRequest.reject(new Error("Old project failed"));
  await flush();
  assert.equal(panel.read("error.value"), null);
  assert.equal(panel.read("loading.value"), true);
  requests.at(-1).resolve([node("B")]);
  await flush();
});

test("late merged answers cannot overwrite the same question in the new project", async (t) => {
  const { panel, requests } = createPanel(t);
  await openAndLoad(panel, requests, "A");
  panel.read("enterNode(nodes.value[0])");
  await nextTick();
  const oldMerged = requests.at(-1);
  panel.props.projectId = "B";
  requests.at(-1).resolve([node("B")]);
  await flush();
  panel.read("enterNode(nodes.value[0])");
  await nextTick();
  requests.at(-1).resolve([{ q: "Shared question", a: "Answer B" }]);
  await flush();
  oldMerged.resolve([{ q: "Shared question", a: "Answer A" }]);
  await flush();
  panel.read('selectQuestion("Shared question", "B")');
  const selection = panel.events.find(([event]) => event === "select-question");
  assert.equal(selection[3], "Answer B");
});

test("changing projects while the merged response body is pending cannot restore old answers", async (t) => {
  let resolveBody;
  const body = new Promise((resolve) => { resolveBody = resolve; });
  const panel = componentSetup(panelPath, { open: false, projectId: "A" }, {
    ...copyHelpers,
    apiFetch: async (url) => ({
      ok: true,
      json: async () => url.includes("/merged?") ? body : [node("A")],
    }),
  });
  t.after(panel.dispose);
  panel.props.open = true;
  await flush();
  panel.read("enterNode(nodes.value[0])");
  await flush();
  panel.props.open = false;
  await nextTick();
  panel.props.projectId = "B";
  resolveBody([{ q: "Shared question", a: "Answer A" }]);
  await flush();
  assert.equal(panel.read("Object.keys(mergedQaCache.value).length"), 0);
});

test("an empty project drops old data without making a fallback request", async (t) => {
  const { panel, requests } = createPanel(t);
  await openAndLoad(panel, requests, "A");
  panel.props.projectId = "";
  assert.equal(panel.read("nodes.value.length"), 0);
  assert.equal(requests.length, 1);
});

test("compact viewport changes move the panel out of the stage and preserve theme ancestry", (t) => {
  const { panel, viewport } = createPanel(t);
  assert.equal(panel.read("isCompactViewport.value"), false);
  viewport.matches = true;
  panel.read("updateCompactViewport()");
  assert.equal(panel.read("isCompactViewport.value"), true);
  viewport.matches = false;
  panel.read("updateCompactViewport()");
  assert.equal(panel.read("isCompactViewport.value"), false);
  const source = readFileSync(panelPath, "utf8");
  assert.match(source, /<Teleport defer to="\.app-shell" :disabled="!isCompactViewport">/);
  const mobile = source.slice(source.indexOf("@media (max-width: 48rem)"));
  assert.match(mobile, /position:\s*fixed;/);
  assert.match(mobile, /height:\s*auto;/);
  assert.match(source, /\.panel-body\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;/);
});
