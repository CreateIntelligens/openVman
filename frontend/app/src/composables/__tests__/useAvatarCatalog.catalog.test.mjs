import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(
  resolve(__dirname, "../useAvatarCatalogCore.ts"),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;

const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { DEFAULT_AVATAR_CATALOG_ENDPOINT, parseAvatarCatalog, fetchErrorMessage } =
  await import(moduleUrl);

test("the catalog defaults to the backend avatar endpoint", () => {
  assert.equal(DEFAULT_AVATAR_CATALOG_ENDPOINT, "/api/avatar");
});

test("parseAvatarCatalog extracts the characters array", () => {
  const chars = parseAvatarCatalog({
    characters: [
      { char_id: "008", label: "008", has_video: true, has_data: true, size_bytes: 1, updated_at: "x" },
      { char_id: "009", label: "009", has_video: true, has_data: true, size_bytes: 2, updated_at: "y" },
    ],
  });
  assert.equal(chars.length, 2);
  assert.deepEqual(chars.map((c) => c.char_id), ["008", "009"]);
});

test("parseAvatarCatalog returns [] when the characters field is missing", () => {
  assert.deepEqual(parseAvatarCatalog({}), []);
  assert.deepEqual(parseAvatarCatalog(null), []);
  assert.deepEqual(parseAvatarCatalog({ characters: "nope" }), []);
});

test("parseAvatarCatalog drops entries without a char_id", () => {
  const chars = parseAvatarCatalog({
    characters: [
      { char_id: "008", label: "008" },
      { label: "missing id" },
      { char_id: "", label: "blank id" },
    ],
  });
  assert.deepEqual(chars.map((c) => c.char_id), ["008"]);
});

test("parseAvatarCatalog fills sensible defaults for partial entries", () => {
  const [c] = parseAvatarCatalog({ characters: [{ char_id: "008" }] });
  assert.equal(c.char_id, "008");
  assert.equal(c.label, "008"); // falls back to char_id
  assert.equal(c.has_video, false);
  assert.equal(c.has_data, false);
  assert.equal(c.size_bytes, 0);
  assert.equal(c.updated_at, "");
});

test("fetchErrorMessage describes an HTTP status failure", () => {
  assert.match(fetchErrorMessage({ status: 500 }), /500/);
});

test("fetchErrorMessage describes a thrown network error", () => {
  assert.match(fetchErrorMessage(new Error("boom")), /boom/);
});
