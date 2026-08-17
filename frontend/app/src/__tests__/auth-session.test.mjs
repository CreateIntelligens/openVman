import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const testDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = resolve(testDir, "..");

function read(relativePath) {
  return readFileSync(resolve(sourceRoot, relativePath), "utf8");
}

test("shared API client includes cookies and centralizes 401 handling", async () => {
  const source = read("api/http.ts");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
  const { apiFetch, setUnauthorizedHandler } = await import(moduleUrl);
  let requestInit;
  let unauthorizedCalls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_input, init) => {
    requestInit = init;
    return new Response(null, { status: 401 });
  };

  try {
    setUnauthorizedHandler(() => {
      unauthorizedCalls += 1;
    });
    await apiFetch("/api/projects");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestInit.credentials, "include");
  assert.equal(unauthorizedCalls, 1);
});

test("Avatar root bootstraps the cookie session before mounting the app", () => {
  const root = read("Root.vue");
  const main = read("main.ts");

  assert.match(root, /auth\.bootstrap\(\)/);
  assert.match(root, /v-else-if="!auth\.account\.value"/);
  assert.match(root, /<App\s*\/>/);
  assert.match(root, /@click="handleLogout"/);
  assert.match(root, /document\.exitFullscreen\(\)/);
  assert.match(root, /if \(!loading && !account\) void leaveFullscreen\(\)/);
  assert.match(main, /import Root from ['"]\.\/Root\.vue['"]/);
});

test("auth API uses cookie endpoints without storing the returned JWT", () => {
  const authApi = read("api/auth.ts");
  const authStore = read("composables/useAuth.ts");

  assert.match(authApi, /"\/api\/auth\/login"/);
  assert.match(authApi, /"\/api\/auth\/logout"/);
  assert.match(authApi, /"\/api\/auth\/me"/);
  assert.doesNotMatch(`${authApi}\n${authStore}`, /localStorage|sessionStorage/);
  assert.match(authStore, /function expireSession\(\)/);
  assert.match(authStore, /replacePath\("\/login"\)/);
});

test("temporary login accepts only a password and exposes the expiry notice", () => {
  const authApi = read("api/auth.ts");
  const authStore = read("composables/useAuth.ts");
  const loginScreen = read("components/auth/LoginScreen.vue");
  const root = read("Root.vue");

  assert.match(authApi, /"\/api\/auth\/temporary-login"/);
  assert.match(authApi, /JSON\.stringify\(\{ password \}\)/);
  assert.match(authStore, /loginTemporary/);
  assert.match(loginScreen, /正式帳號/);
  assert.match(loginScreen, /臨時密碼/);
  assert.match(loginScreen, /v-if="mode === 'formal'"/);
  assert.match(root, /remaining_seconds/);
  assert.match(root, /expires_at/);
  assert.match(root, /剩餘 \{\{ remainingLabel \}\}/);
});

test("resource defaults are resolved only against the authorized lists", () => {
  const app = read("App.vue");

  assert.match(app, /PREFERRED_PROJECT_ID = "proj-b85afb8bb6"/);
  assert.match(app, /PREFERRED_CHARACTER_ID = "0713"/);
  assert.match(app, /PREFERRED_VOICE_PROVIDER = "indextts"/);
  assert.match(app, /PREFERRED_VOICE_ID = "hayley"/);
  assert.match(app, /items\.some\(\(project\) => project\.project_id === preferred\)/);
  assert.match(app, /characters\.value\.some\(\(character\) => character\.id === preferred\)/);
  assert.doesNotMatch(app, /fallbackCharacters/);
  assert.match(app, /未獲授權，已改用/);
});
