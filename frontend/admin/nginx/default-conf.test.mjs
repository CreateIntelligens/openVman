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
      /location = \/openvman-avatar-sdk\.js \{[\s\S]*alias \/usr\/share\/nginx\/html\/openvman-avatar-sdk\.js/,
    );
    expect(source).not.toContain("avatar-sdk:80");
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

  it("does not proxy retired public embed backend routes", () => {
    const embedApi = source.indexOf("location /api/embed/");
    const embedSocket = source.indexOf("location /ws/embed/");
    const generalApi = source.indexOf("location /api/ {");
    const generalSocket = source.indexOf("location /ws/ {");

    expect(source).toMatch(/location \/api\/embed\/ \{\s*return 410;/);
    expect(source).toMatch(/location \/ws\/embed\/ \{\s*return 410;/);
    expect(embedApi).toBeLessThan(generalApi);
    expect(embedSocket).toBeLessThan(generalSocket);
  });

  it("proxies public and authorized character resources without unsafe shared caching", () => {
    const assetsLocation = source.match(/location \/assets\/ \{([\s\S]*?)\n    \}/)?.[1];

    expect(assetsLocation).toContain('Access-Control-Allow-Origin "*"');
    expect(assetsLocation).toContain(
      "proxy_set_header Authorization $http_authorization;",
    );
    expect(assetsLocation).not.toContain('Cache-Control "public');
  });

  it("proxies the public character list with CORS and short caching", () => {
    const charactersLocation = source.match(
      /location = \/characters \{([\s\S]*?)\n    \}/,
    )?.[1];

    expect(charactersLocation).toContain("proxy_pass $backend$request_uri;");
    expect(charactersLocation).toContain('Access-Control-Allow-Origin "*"');
    expect(charactersLocation).toContain('Cache-Control "public, max-age=300"');
  });

  it.each(["embedding", "vlm"])(
    "protects the %s GPU edge route with upstream bearer auth and limits",
    (service) => {
      const location = source.match(
        new RegExp(`location ~ \\^/api/gpu/${service}/\\(\\.\\*\\)\\$ \\{([\\s\\S]*?)\\n    \\}`),
      )?.[1];

      expect(location).toContain("proxy_set_header Authorization $http_authorization;");
      expect(location).toContain("limit_req zone=gpu_inference_rate burst=4 nodelay;");
      expect(location).toContain("limit_req_status 429;");
      expect(location).toContain("limit_conn gpu_inference_conn 2;");
      expect(location).toContain("limit_conn_status 429;");
      expect(location).toContain("client_body_timeout 15s;");
    },
  );

  it("defines bounded shared GPU inference rate and connection zones", () => {
    expect(source).toContain(
      "limit_req_zone $binary_remote_addr zone=gpu_inference_rate:10m rate=2r/s;",
    );
    expect(source).toContain(
      "limit_conn_zone $binary_remote_addr zone=gpu_inference_conn:10m;",
    );
  });
});
