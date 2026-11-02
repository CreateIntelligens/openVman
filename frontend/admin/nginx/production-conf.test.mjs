import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "production.conf"), "utf8");

function locationBody(prefix) {
  const body = source.match(new RegExp(`location ${prefix} \\{([\\s\\S]*?)\\n\\}`))?.[1];
  expect(body, `location ${prefix}`).toBeDefined();
  return body;
}

describe("nginx production admin routes", () => {
  it("makes browsers revalidate index.html so it never names deleted chunks", () => {
    const admin = locationBody("/admin/");

    // SPA 路由由 try_files 內部轉回 /admin/index.html，再次比對還是這個 location。
    expect(admin).toContain("try_files $uri $uri/ /admin/index.html;");
    expect(admin).toContain('add_header Cache-Control "no-cache";');
    expect(source).not.toContain("location = /admin/index.html");
  });

  it("caches hashed assets long and immutably", () => {
    const assets = locationBody("/admin/assets/");

    expect(assets).toContain("expires 1y;");
    expect(assets).toContain('add_header Cache-Control "public, immutable";');
  });

  it("keeps a missing asset a 404 that browsers will not cache", () => {
    const assets = locationBody("/admin/assets/");

    // 落回 index.html 的話，舊 chunk 會以 200 HTML 回應，瀏覽器只報 MIME 錯誤。
    expect(assets).not.toContain("try_files");
    expect(assets).not.toContain("index.html");
    // always 會讓 404 也帶上 immutable。
    expect(assets).not.toContain("always");
  });
});
