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
  assert.match(root, /runLogout/);
  assert.match(root, /cleanupLoggedOutSession/);
  assert.match(main, /import Root from ['"]\.\/Root\.vue['"]/);
});

async function loadSessionCleanup() {
  const source = read("sessionCleanup.ts");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
  return import(moduleUrl);
}

test("logout cleans up fullscreen before calling the auth API", async () => {
  const { runLogout } = await loadSessionCleanup();
  const calls = [];
  let loggingOut = false;

  await runLogout({
    isLoggingOut: () => loggingOut,
    setLoggingOut: (value) => {
      loggingOut = value;
    },
    cleanup: async () => {
      calls.push("cleanup");
    },
    logout: async () => {
      calls.push("logout");
    },
  });

  assert.deepEqual(calls, ["cleanup", "logout"]);
  assert.equal(loggingOut, false);
});

test("fullscreen and keyboard cleanup failures do not block logout", async () => {
  const { leaveFullscreen, runLogout } = await loadSessionCleanup();
  const calls = [];
  let loggingOut = false;
  const doc = {
    fullscreenElement: {},
    exitFullscreen: async () => {
      calls.push("exitFullscreen");
      throw new Error("browser failure");
    },
  };
  const nav = {
    keyboard: {
      unlock: () => {
        calls.push("unlock");
        throw new Error("browser failure");
      },
    },
  };

  await runLogout({
    isLoggingOut: () => loggingOut,
    setLoggingOut: (value) => {
      loggingOut = value;
    },
    cleanup: () => leaveFullscreen(doc, nav),
    logout: async () => {
      calls.push("logout");
    },
  });

  assert.deepEqual(calls, ["exitFullscreen", "unlock", "logout"]);
});

test("session loss after loading requests fullscreen cleanup", async () => {
  const { cleanupLoggedOutSession } = await loadSessionCleanup();
  let cleanupCalls = 0;
  const cleanup = async () => {
    cleanupCalls += 1;
  };

  cleanupLoggedOutSession(true, null, cleanup);
  cleanupLoggedOutSession(false, { id: "user-a" }, cleanup);
  cleanupLoggedOutSession(false, null, cleanup);
  await Promise.resolve();

  assert.equal(cleanupCalls, 1);
});

test("repeated logout calls share the in-progress guard", async () => {
  const { runLogout } = await loadSessionCleanup();
  let loggingOut = false;
  let releaseCleanup;
  let logoutCalls = 0;
  const cleanupGate = new Promise((resolve) => {
    releaseCleanup = resolve;
  });
  const operation = {
    isLoggingOut: () => loggingOut,
    setLoggingOut: (value) => {
      loggingOut = value;
    },
    cleanup: () => cleanupGate,
    logout: async () => {
      logoutCalls += 1;
    },
  };

  const first = runLogout(operation);
  const second = runLogout(operation);
  await second;
  assert.equal(logoutCalls, 0);
  releaseCleanup();
  await first;

  assert.equal(logoutCalls, 1);
  assert.equal(loggingOut, false);
});

test("auth API uses cookie endpoints without storing the returned JWT", () => {
  const authApi = read("api/auth.ts");
  const authStore = read("composables/useAuth.ts");

  assert.match(authApi, /"\/api\/auth\/login"/);
  assert.match(authApi, /"\/api\/auth\/logout"/);
  assert.match(authApi, /"\/api\/auth\/me"/);
  assert.doesNotMatch(`${authApi}\n${authStore}`, /localStorage|sessionStorage/);
  assert.match(authStore, /function expireSession\(\)/);
  assert.match(authStore, /publicAppPath\("\/login"\)/);
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
