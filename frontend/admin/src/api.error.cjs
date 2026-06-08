const assert = require("node:assert/strict");
const fs = require("node:fs");
const { transformSync } = require("esbuild");

require.extensions[".ts"] = (module, filename) => {
  const source = fs.readFileSync(filename, "utf8");
  const { code } = transformSync(source, {
    format: "cjs",
    loader: "ts",
    sourcemap: "inline",
    target: "es2020",
  });
  module._compile(code, filename);
};

const { fetchHealth } = require("./api/metrics.ts");
const { fetchProjects } = require("./api/projects.ts");

async function testFetchHealthIncludesBackendErrorDetail() {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error_code: "UPLOAD_FAILED",
        message: "檔案上傳失敗",
        error: "storage_quota_exceeded",
      }),
      {
        status: 413,
        headers: { "Content-Type": "application/json" },
      },
    );

  try {
    await assert.rejects(
      () => fetchHealth(),
      (error) => error instanceof Error && error.message === "檔案上傳失敗：storage_quota_exceeded",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function testFetchProjectsUsesApiBase() {
  const originalFetch = globalThis.fetch;
  let calledUrl = "";
  globalThis.fetch = async (url) => {
    calledUrl = String(url);
    return new Response(JSON.stringify({ projects: [], project_count: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    await fetchProjects();
    assert.equal(calledUrl, "/api/projects");
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function main() {
  await testFetchHealthIncludesBackendErrorDetail();
  await testFetchProjectsUsesApiBase();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
