import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const conf = readFileSync(resolve(here, "../../nginx/default.conf"), "utf8");

function block(location) {
  const start = conf.indexOf(`location ${location} {`);
  assert.notEqual(start, -1, `missing location ${location}`);
  return conf.slice(start, conf.indexOf("}", start));
}

test("/login, a client-side route, survives a reload", () => {
  assert.match(block("= /login"), /try_files \/index\.html =404;/);
  assert.match(block("= /login"), /no-cache/);
});

test("other missing paths stay 404 so stale chunks can trigger a reload", () => {
  assert.match(block("/"), /try_files \$uri \$uri\/ =404;/);
});
