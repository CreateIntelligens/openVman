import assert from "node:assert/strict";
import { test } from "node:test";

import { checkMotionAccess } from "../../public/experiments/avatar-motion/access-check.js";

test("an anonymous visitor is guided to login without requesting protected character data", async () => {
  const paths = [];
  const result = await checkMotionAccess(async (path) => { paths.push(path); return new Response(null, { status: 401 }); });
  assert.equal(result.state, "login-required");
  assert.match(result.message, /登入/);
  assert.deepEqual(paths, ["/api/v1/auth/admin-me"]);
});

test("login can recover in the same page without initializing a failed WASM instance", async () => {
  let loggedIn = false;
  const request = async (path) => new Response(null, { status: path.includes("admin-me") && !loggedIn ? 401 : 200 });
  assert.equal((await checkMotionAccess(request)).state, "login-required");
  loggedIn = true;
  assert.equal((await checkMotionAccess(request)).state, "available");
});

test("a custom protected bundle is checked after the session without changing the default", async () => {
  const assetUrl = "/static/characters/0624/motion-lab/hciot-v1/combined_data.json.gz";
  const paths = [];
  const fetcher = async (path, options) => {
    paths.push(path);
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    return new Response(null, { status: 200 });
  };
  assert.equal((await checkMotionAccess(fetcher, assetUrl)).state, "available");
  assert.deepEqual(paths, ["/api/v1/auth/admin-me", assetUrl]);
});

test("an anonymous visitor never requests even a custom protected bundle", async () => {
  const paths = [];
  const result = await checkMotionAccess(async (path) => {
    paths.push(path);
    return new Response(null, { status: 401 });
  }, "/static/characters/0624/motion-lab/hciot-v1/combined_data.json.gz");
  assert.equal(result.state, "login-required");
  assert.deepEqual(paths, ["/api/v1/auth/admin-me"]);
});

test("authenticated users without character access are not treated as anonymous", async () => {
  const result = await checkMotionAccess(async (path) => new Response(null, { status: path.includes("admin-me") ? 200 : 403 }));
  assert.equal(result.state, "unavailable");
  assert.match(result.message, /無權/);
});

test("missing files and network failures are explained before starting the renderer", async () => {
  const missing = await checkMotionAccess(async (path) => new Response(null, { status: path.includes("admin-me") ? 200 : 404 }));
  assert.equal(missing.state, "unavailable");
  assert.match(missing.message, /HTTP 404/);
  const offline = await checkMotionAccess(async () => { throw new Error("offline"); });
  assert.equal(offline.state, "unavailable");
  assert.match(offline.message, /無法連線/);
});
