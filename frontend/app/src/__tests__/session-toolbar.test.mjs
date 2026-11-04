import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const root = readFileSync(new URL("../Root.vue", import.meta.url), "utf8");

test("the account bar never floats over a single-column layout", () => {
  assert.match(
    root,
    /max-width: 68\.75rem\) \{\s*\.app-shell:not\(\.immersive\) ~ \.session-toolbar \{\s*position: static;/,
  );
});

test("the account bar stays on screen where the page cannot scroll", () => {
  assert.match(
    root,
    /min-width: 48\.0625rem\) and \(max-width: 68\.75rem\) \{\s*\.authenticated-app:has\(> \.app-shell:not\(\.immersive\)\) \{\s*display: flex;[^}]*height: 100dvh;/,
  );
});
