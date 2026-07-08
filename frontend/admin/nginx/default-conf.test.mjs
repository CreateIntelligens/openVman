import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "http.d/default.conf"), "utf8");

describe("nginx default config", () => {
  it("proxies avatar background assets to backend before avatar frontend fallback", () => {
    const backgroundsLocation = source.indexOf("location /backgrounds/");
    const avatarFallback = source.indexOf("location / {");

    expect(backgroundsLocation).not.toBe(-1);
    expect(avatarFallback).not.toBe(-1);
    expect(backgroundsLocation).toBeLessThan(avatarFallback);
    expect(source).toMatch(/location \/backgrounds\/[\s\S]*proxy_pass \$backend\$request_uri;/);
  });

  it("proxies avatar mascot assets to backend before avatar frontend fallback", () => {
    const mascotsLocation = source.indexOf("location /mascots/");
    const avatarFallback = source.indexOf("location / {");

    expect(mascotsLocation).not.toBe(-1);
    expect(avatarFallback).not.toBe(-1);
    expect(mascotsLocation).toBeLessThan(avatarFallback);
    expect(source).toMatch(/location \/mascots\/[\s\S]*proxy_pass \$backend\$request_uri;/);
  });
});
