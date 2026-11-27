import { afterEach, describe, expect, it, vi } from "vitest";

import { EMPTY_CONTENT_HASH, fetchPersonaAgents, savePersonaSoul } from "./personas";

afterEach(() => vi.restoreAllMocks());

function mockFetch(payload: unknown, status = 200) {
  return vi.spyOn(global, "fetch").mockResolvedValue({
    ok: status < 400,
    status,
    json: async () => payload,
    headers: new Headers({ "content-type": "application/json" }),
  } as Response);
}

describe("persona document api", () => {
  it("pins the empty-file version to Brain's hash of an empty string", async () => {
    // Brain 的 content_hash 是 sha256 十六進位的前 16 碼；Brain 測試釘住同一個值。
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode("")));
    const hex = Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
    expect(EMPTY_CONTENT_HASH).toBe(hex.slice(0, 16));
  });

  it("treats a missing AGENTS.md as an empty file version", async () => {
    mockFetch({ detail: "找不到角色的人設內容。" }, 404);
    await expect(fetchPersonaAgents("support", "p1")).resolves.toEqual({
      content: "", exists: false, content_hash: EMPTY_CONTENT_HASH,
    });
  });

  it("sends base_hash only when there is one", async () => {
    const fetch = mockFetch({ status: "ok", content_hash: "next" });
    await savePersonaSoul("default", "內容", "p1", "base");
    await savePersonaSoul("default", "內容", "p1");
    const bodies = fetch.mock.calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)));
    expect(bodies[0]).toMatchObject({ base_hash: "base", content: "內容", project_id: "p1" });
    expect(bodies[1]).not.toHaveProperty("base_hash");
  });
});
