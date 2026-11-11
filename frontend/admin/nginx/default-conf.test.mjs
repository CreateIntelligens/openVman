import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "http.d/default.conf"), "utf8");

// 退役路徑一律不得留下任何 location —— 沒有 301、alias、rewrite，也沒有
// 410 過渡期。這些前綴只要再出現，就是有人偷偷把相容層加回來了。
const RETIRED_LOCATIONS = [
  "/embed/",
  "/api/embed/",
  "/ws/embed/",
  "/vman-embed.js",
  "/embed/avatar",
  "/assets/",
  "/mascots/",
  "/static/mascots/",
  "/backgrounds/",
  "/tts/",
  "/uploads",
  "/jobs/",
  "/documents/",
  "/admin/dlq",
  "/characters",
  "/openvman-avatar-sdk.js",
  "/sdk/runtime/",
  "/v1/tts/",
  "/v1/usage/",
];

function locationBody(prefix) {
  const escaped = prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return source.match(
    new RegExp(`location (?:= )?${escaped} \\{([\\s\\S]*?)\\n    \\}`),
  )?.[1];
}

describe("nginx default config", () => {
  it("copies the complete shared engine into the SDK image build stage", () => {
    const dockerfile = readFileSync(resolve(__dirname, "../Dockerfile"), "utf8");
    const sdkStage = dockerfile.split(" AS avatar-sdk-builder")[1]?.split("\nFROM ")[0];

    // 整個目錄才會同時包含 .mjs、.d.mts 與引擎內部相依，不能只複製入口 JS。
    expect(sdkStage).toMatch(/^COPY frontend\/shared\/avatar-engine \/shared\/avatar-engine$/m);
    expect(sdkStage).toContain("RUN pnpm test");
  });

  it.each(RETIRED_LOCATIONS)("carries no location for the retired %s", (prefix) => {
    // /static/backgrounds/ 之類的現行路徑本身含有舊前綴字串，所以比對整個
    // location 指令而不是裸字串。
    expect(source).not.toMatch(
      new RegExp(`location (?:= |\\^~ )?${prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[ {]`),
    );
  });

  it("proxies avatar background files to backend before the avatar fallback", () => {
    const backgrounds = source.indexOf("location /static/backgrounds/");
    const avatarFallback = source.indexOf("location / {");

    expect(backgrounds).not.toBe(-1);
    expect(backgrounds).toBeLessThan(avatarFallback);
    expect(source).toMatch(
      /location \/static\/backgrounds\/[\s\S]*proxy_pass \$backend\$request_uri;/,
    );
  });

  it("serves the avatar SDK bundle and shared engine under /static/sdk with CORS", () => {
    expect(source).toMatch(
      /location = \/static\/sdk\/openvman-avatar-sdk\.js \{[\s\S]*Access-Control-Allow-Origin "\*"/,
    );
    expect(source).toMatch(
      /location = \/static\/sdk\/openvman-avatar-sdk\.js \{[\s\S]*alias \/usr\/share\/nginx\/html\/openvman-avatar-sdk\.js/,
    );
    expect(source).not.toContain("avatar-sdk:80");
    const engine = locationBody("/static/sdk/engine/");
    expect(engine).toContain("rewrite ^/static/sdk/engine/(.*)$ /avatar-engine/$1 break;");
    expect(engine).toContain("proxy_pass $avatar$uri$is_args$args;");
    expect(engine).toContain('Access-Control-Allow-Origin "*"');
    expect(source).not.toContain("OpenVmanAvatarRuntime");
    expect(engine).toContain("proxy_hide_header Access-Control-Allow-Origin;");
  });

  it("proxies public and authorized character files without unsafe shared caching", () => {
    const characters = locationBody("/static/characters/");

    // Backend 可能反射宿主 Origin；先移除該標頭，避免與 edge 的 * 重複而被瀏覽器拒絕。
    expect(characters).toContain("proxy_hide_header Access-Control-Allow-Origin;");
    expect(characters.match(/add_header Access-Control-Allow-Origin/g)).toHaveLength(1);
    expect(characters).toContain('add_header Access-Control-Allow-Origin "*" always;');
    expect(characters).toContain("proxy_set_header Authorization $http_authorization;");
    expect(characters).not.toContain('Cache-Control "public');
  });

  it("keeps every /static/ path on the backend instead of the avatar fallback", () => {
    const catchAll = source.indexOf("location /static/ {");
    const avatarFallback = source.indexOf("location / {");

    expect(catchAll).not.toBe(-1);
    expect(catchAll).toBeLessThan(avatarFallback);
    expect(locationBody("/static/")).toContain("proxy_pass $backend$request_uri;");
  });

  it("limits the OpenAI-compatible family to audio", () => {
    expect(source).toContain("location /v1/audio/ {");
    expect(locationBody("/v1/audio/")).toContain("proxy_pass $backend$request_uri;");
  });

  it("routes the application API through a single /api/ location with websocket upgrade", () => {
    const api = locationBody("/api/");

    expect(api).toContain("include /etc/nginx/http.d/websocket.conf;");
    expect(api).toContain("proxy_pass $backend$request_uri;");
  });

  it("caps API bodies at 100m and only widens the avatar job upload to 200m", () => {
    // 外圈 host nginx 也是 100m；後端各上傳端點再各自設更小的上限。
    expect(locationBody("/api/")).toContain("client_max_body_size 100m;");
    const jobs = locationBody("/api/v1/avatar/jobs");
    expect(jobs).toContain("client_max_body_size 200m;");
    expect(jobs).toContain("proxy_pass $backend$request_uri;");
  });

  it("streams TTS unbuffered ahead of the generic API location", () => {
    const stream = source.indexOf("location /api/v1/tts/stream {");
    const api = source.indexOf("location /api/ {");

    expect(stream).not.toBe(-1);
    expect(stream).toBeLessThan(api);
    expect(locationBody("/api/v1/tts/stream")).toContain("proxy_buffering off;");
  });

  // 兩個服務的路徑一致，都是 /api/<service>/。
  it.each(["embedding", "vlm"])(
    "protects the %s inference edge route with upstream bearer auth and limits",
    (service) => {
      const location = source.match(
        new RegExp(`location ~ \\^/api/${service}/\\(\\.\\*\\)\\$ \\{([\\s\\S]*?)\\n    \\}`),
      )?.[1];

      expect(location).toContain("proxy_set_header Authorization $http_authorization;");
      expect(location).toContain("limit_req zone=gpu_inference_rate burst=4 nodelay;");
      expect(location).toContain("limit_req_status 429;");
      expect(location).toContain("limit_conn gpu_inference_conn 2;");
      expect(location).toContain("limit_conn_status 429;");
      expect(location).toContain("client_body_timeout 15s;");
    },
  );

  it("serves shared inference under /api without the gpu prefix", () => {
    // 兩個推論服務都掛在 /api 下；/api/gpu/* 是已退役的舊前綴。
    expect(source).toContain("location ~ ^/api/embedding/(.*)$");
    expect(source).toContain("location ~ ^/api/vlm/(.*)$");
    expect(source).not.toContain("/api/gpu/");
  });

  it("maps the embedding base URL onto the embed endpoint", () => {
    // 精確比對必須排在前綴規則之前，consumer 才不用打 /api/embedding/embed。
    const exact = source.indexOf("location = /api/embedding {");
    const prefix = source.indexOf("location ~ ^/api/embedding/(.*)$");

    expect(exact).not.toBe(-1);
    expect(exact).toBeLessThan(prefix);
    expect(locationBody("/api/embedding")).toContain(
      "http://embedding:8009/embed$is_args$args",
    );
  });

  it("defines bounded shared GPU inference rate and connection zones", () => {
    expect(source).toContain(
      "limit_req_zone $binary_remote_addr zone=gpu_inference_rate:10m rate=2r/s;",
    );
    expect(source).toContain(
      "limit_conn_zone $binary_remote_addr zone=gpu_inference_conn:10m;",
    );
  });
});
