import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const modulePath = resolve(__dirname, "../mascotCatalog.ts");

async function loadModule() {
  assert.ok(
    existsSync(modulePath),
    "expected mascot catalog module to exist",
  );
  const source = readFileSync(modulePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
  return import(moduleUrl);
}

test("mascot catalog exposes a default option", async () => {
  const { DEFAULT_MASCOT_ID, MASCOT_CATALOG, resolveMascotOption } =
    await loadModule();

  assert.ok(DEFAULT_MASCOT_ID);
  assert.ok(MASCOT_CATALOG.length >= 2);
  assert.equal(resolveMascotOption("").id, DEFAULT_MASCOT_ID);
  assert.equal(resolveMascotOption("missing").id, DEFAULT_MASCOT_ID);
});

test("qqman mascot uses the Frieren display name", async () => {
  const { MASCOT_CATALOG } = await loadModule();
  const qqmanMascot = MASCOT_CATALOG.find((mascot) => mascot.id === "qqman");

  assert.equal(qqmanMascot?.label, "Frieren");
});

test("mascot widget src encodes a 2D model option", async () => {
  const { buildMascotWidgetSrc } = await loadModule();
  const src = buildMascotWidgetSrc({
    id: "haru",
    label: "Haru",
    engine: "2d",
    modelUrl: "https://example.com/haru.model3.json",
    fit: "half",
  });

  const url = new URL(src, "https://openvman.test");
  assert.equal(url.pathname, "/vendor/ai-avatar-bot/widget.html");
  assert.equal(url.searchParams.get("model"), "https://example.com/haru.model3.json");
  assert.equal(url.searchParams.get("engine"), "2d");
  assert.equal(url.searchParams.get("fit"), "half");
  assert.equal(url.searchParams.has("vrm"), false);
});

test("mascot widget src encodes a 3D VRM option", async () => {
  const { buildMascotWidgetSrc } = await loadModule();
  const src = buildMascotWidgetSrc({
    id: "vrm",
    label: "VRM",
    engine: "3d",
    vrmUrl: "https://example.com/model.vrm",
  });

  const url = new URL(src, "https://openvman.test");
  assert.equal(url.searchParams.get("vrm"), "https://example.com/model.vrm");
  assert.equal(url.searchParams.get("engine"), "3d");
  assert.equal(url.searchParams.has("vrmScale"), false);
  assert.equal(url.searchParams.has("vrmCameraY"), false);
  assert.equal(url.searchParams.has("vrmLookAtY"), false);
  assert.equal(url.searchParams.has("vrmCameraZ"), false);
  assert.equal(url.searchParams.has("model"), false);
});

test("mascot api records convert to switcher options", async () => {
  const { toMascotOption, resolveMascotOption } = await loadModule();
  const option = toMascotOption({
    mascot_id: "custom",
    label: "自訂小助理",
    engine: "3d",
    model_url: "",
    vrm_url: "/mascots/custom/model.vrm",
    fit: "",
  });

  assert.equal(option.id, "custom");
  assert.equal(option.label, "自訂小助理");
  assert.equal(option.vrmUrl, "/mascots/custom/model.vrm");
  assert.equal(resolveMascotOption("custom", [option]).id, "custom");
});

test("built-in VRM mascots rely on widget auto-fit instead of per-model framing", async () => {
  const { MASCOT_CATALOG } = await loadModule();
  const vrmMascots = MASCOT_CATALOG.filter((mascot) => mascot.engine === "3d");

  assert.ok(vrmMascots.length >= 1);
  for (const mascot of vrmMascots) {
    assert.equal(mascot.vrmScale, undefined);
    assert.equal(mascot.vrmCameraY, undefined);
    assert.equal(mascot.vrmLookAtY, undefined);
    assert.equal(mascot.vrmCameraZ, undefined);
  }
});
