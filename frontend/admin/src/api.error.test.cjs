const assert = require("node:assert/strict");

const { fetchHealth, fetchProjects } = require("./api.ts");

async function testFetchHealthPrefersFriendlyMessage() {
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
      (error) => error instanceof Error && error.message === "檔案上傳失敗",
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
  await testFetchHealthPrefersFriendlyMessage();
  await testFetchProjectsUsesApiBase();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
