import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
async function load(file) {
  const { outputFiles } = await build({
    entryPoints: [resolve(__dirname, file)],
    bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`);
}
const { resolveLockedLanguage, languageFromSearch, normalizeLockedLanguage } = await load("../../types/lockedLanguage.ts");
const { createGreetingScheduler, fetchGreeting } = await load("../greeting.ts");

test("the URL language beats the saved one, which beats no lock", () => {
  assert.equal(resolveLockedLanguage("?lang=es", "en"), "es");
  assert.equal(resolveLockedLanguage("", "en"), "en");
  assert.equal(resolveLockedLanguage("", ""), "");
});

test("values outside zh/en/es/ja/ko are ignored, in the URL and in storage", () => {
  assert.equal(languageFromSearch("?lang=fr"), "");
  assert.equal(languageFromSearch("?lang=nan"), "");
  assert.equal(languageFromSearch("?lang="), "");
  assert.equal(resolveLockedLanguage("?lang=fr", "ko"), "ko", "a bad URL value falls through to the saved language");
  assert.equal(normalizeLockedLanguage("klingon"), "");
  for (const code of ["zh", "en", "es", "ja", "ko"]) assert.equal(languageFromSearch(`?x=1&lang=${code}`), code);
});

const KEY = { language: "es", personaId: "walter", projectId: "p1" };

function scheduler({ responses = [], key = () => KEY } = {}) {
  const played = [];
  const fetched = [];
  const queue = [...responses];
  const s = createGreetingScheduler({
    current: key,
    fetch: async (k) => {
      fetched.push(k);
      const next = queue.length ? queue.shift() : { text: "Hola" };
      if (next instanceof Error) throw next;
      return next;
    },
    play: (greeting) => { played.push(greeting.text); },
  });
  return { s, played, fetched };
}

test("a greeting plays once per language, persona and project, however often state is re-read", async () => {
  const { s, played, fetched } = scheduler();
  await s.sync(); await s.sync(); await Promise.all([s.sync(), s.sync()]);
  assert.deepEqual(played, ["Hola"]);
  assert.equal(fetched.length, 1);
});

test("changing the language plays that language's greeting again", async () => {
  let key = KEY;
  const { s, played, fetched } = scheduler({ key: () => key, responses: [{ text: "Hola" }, { text: "Hello" }] });
  await s.sync();
  key = { ...KEY, language: "en" };
  await s.sync();
  key = KEY;
  await s.sync();
  assert.deepEqual(played, ["Hola", "Hello"]);
  assert.deepEqual(fetched.map((k) => k.language), ["es", "en"]);
});

test("a missing greeting (404) or a failed request stays silent", async () => {
  const { s, played } = scheduler({ responses: [null] });
  await assert.doesNotReject(s.sync());
  assert.deepEqual(played, []);

  const failing = scheduler({ responses: [new Error("network down"), { text: "Hola" }] });
  await assert.doesNotReject(failing.s.sync());
  assert.deepEqual(failing.played, []);
  await failing.s.sync();
  assert.deepEqual(failing.played, ["Hola"], "a network failure may be retried on the next change");
});

test("nothing plays until the avatar is ready, and a stale answer is dropped", async () => {
  let key = null;
  const { s, played, fetched } = scheduler({ key: () => key });
  await s.sync();
  assert.equal(fetched.length, 0);

  let release;
  const slow = createGreetingScheduler({
    current: () => key,
    fetch: () => new Promise((resolve) => { release = () => resolve({ text: "Hola" }); }),
    play: (g) => played.push(g.text),
  });
  key = KEY;
  const pending = slow.sync();
  key = { ...KEY, language: "en" };
  release();
  await pending;
  assert.deepEqual(played, [], "the language changed while the request was in flight");
});

test("reset lets the same set play again for the next visitor", async () => {
  const { s, played } = scheduler();
  await s.sync();
  s.reset();
  await s.sync();
  assert.deepEqual(played, ["Hola", "Hola"]);
});

test("fetchGreeting asks for the language, persona and project and maps 404 to null", async () => {
  const urls = [];
  const ok = (body) => async (url) => { urls.push(url); return { ok: true, status: 200, json: async () => body }; };
  assert.deepEqual(await fetchGreeting(ok({ language: "es", text: "Hola", voice: "v-es" }), KEY), { text: "Hola", voice: "v-es" });
  assert.deepEqual(await fetchGreeting(ok({ text: "Hola", voice: null }), KEY), { text: "Hola" });
  const url = new URL(urls[0], "http://x");
  assert.equal(url.pathname, "/api/v1/personas/greeting");
  assert.deepEqual(Object.fromEntries(url.searchParams), { language: "es", persona_id: "walter", project_id: "p1" });
  assert.equal(await fetchGreeting(async () => ({ ok: false, status: 404, json: async () => ({}) }), KEY), null);
  assert.equal(await fetchGreeting(ok({ text: "  " }), KEY), null);
});
