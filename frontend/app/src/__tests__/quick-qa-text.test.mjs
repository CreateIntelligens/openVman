import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../components/controls/quickQaText.ts"), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { quickQaLanguage, quickQaCopy, visibleNodes, languageOfLabel } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);
const panel = readFileSync(resolve(__dirname, "../components/controls/QuickQaPanel.vue"), "utf8");

test("the panel speaks the language category the visitor picked", () => {
  assert.equal(quickQaLanguage([]), "zh");
  assert.equal(quickQaLanguage([{ label: "English" }, { label: "EVAK Pump FAQ (50)" }]), "en");
  assert.equal(quickQaLanguage([{ label: " español " }]), "es");
  assert.equal(quickQaLanguage([{ label: "鶴記" }, { label: "日本語" }]), "ja");
  assert.equal(quickQaLanguage([{ label: "EVAK 沉水泵浦型錄 Q&A" }]), "zh");
  assert.equal(quickQaCopy("en").back, "Back");
  assert.equal(quickQaCopy("es").back, "Volver");
  assert.equal(languageOfLabel("한국어"), "ko");
});

test("every language has the same copy keys", () => {
  const keys = Object.keys(quickQaCopy("zh")).sort();
  for (const language of ["en", "es", "ja", "ko"]) {
    assert.deepEqual(Object.keys(quickQaCopy(language)).sort(), keys, language);
  }
});

test("topics hidden in the admin console stay out of the menu", () => {
  const nodes = [{ node_id: "a", hidden: false }, { node_id: "b", hidden: true }, { node_id: "c" }];
  assert.deepEqual(visibleNodes(nodes).map((n) => n.node_id), ["a", "c"]);
  assert.deepEqual(visibleNodes(undefined), []);
});

test("the panel has no hard-coded Chinese copy left and filters hidden topics", () => {
  const template = panel.slice(0, panel.indexOf("<script"));
  assert.doesNotMatch(template, /[一-鿿]/, "template text comes from quickQaCopy");
  assert.match(panel, /visibleNodes\(currentNode\.value\.children\)/);
  assert.match(panel, /visibleNodes\(nodes\.value\)/);
});
