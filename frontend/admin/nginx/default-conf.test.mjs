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

  it("serves the direct avatar SDK and branded runtime resources with CORS", () => {
    expect(source).toMatch(
      /location = \/openvman-avatar-sdk\.js \{[\s\S]*Access-Control-Allow-Origin "\*"/,
    );
    expect(source).toMatch(
      /location = \/openvman-avatar-sdk\.js \{[\s\S]*proxy_pass \$avatar_sdk\/openvman-avatar-sdk\.js/,
    );
    expect(source).toMatch(
      /location = \/sdk\/runtime\/OpenVmanAvatarRuntime\.wasm \{[\s\S]*application\/wasm/,
    );
    expect(source).toMatch(
      /location = \/sdk\/runtime\/OpenVmanAvatarRuntime\.js \{[\s\S]*DHLiveMini2\.js/,
    );
    expect(source.match(/proxy_hide_header Access-Control-Allow-Origin;/g)).toHaveLength(2);
  });

  it("does not expose the retired iframe integration routes", () => {
    expect(source).toMatch(/location = \/embed\/avatar \{\s*return 410;/);
    expect(source).toMatch(/location = \/vman-embed\.js \{\s*return 410;/);
    expect(source).toMatch(/location \/embed\/ \{\s*return 410;/);
    expect(source).not.toContain("/srv/openvman/embed");
  });

  it("allows cross-origin character resources for the direct SDK", () => {
    const assetsLocation = source.match(/location \/assets\/ \{([\s\S]*?)\n    \}/)?.[1];

    expect(assetsLocation).toContain('Access-Control-Allow-Origin "*"');
  });
});
