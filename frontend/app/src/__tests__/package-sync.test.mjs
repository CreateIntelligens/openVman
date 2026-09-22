import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

test("frontend/app and frontend/admin have identical @ricky0123/vad-web version", () => {
  const appPkg = JSON.parse(readFileSync(resolve(__dirname, "../../package.json"), "utf-8"));
  const adminPkg = JSON.parse(readFileSync(resolve(__dirname, "../../../admin/package.json"), "utf-8"));

  // 比對原字串，不剝掉 ^ 或 ~：帶範圍符號的一邊 pnpm update 之後就會悄悄跟另一邊
  // 分歧。shared/speech/vad-version.test.ts 是同一個檢查，那份只有 admin 的 vitest
  // 會跑，這份給 app 的 node --test。
  const appVad = appPkg.dependencies?.["@ricky0123/vad-web"] || "";
  const adminVad = adminPkg.dependencies?.["@ricky0123/vad-web"] || "";
  assert.match(appVad, /^\d/, "app 的 vad-web 要釘死版本");
  assert.match(adminVad, /^\d/, "admin 的 vad-web 要釘死版本");

  assert.equal(appVad, adminVad);
  assert.equal(appVad, "0.0.30");
});
