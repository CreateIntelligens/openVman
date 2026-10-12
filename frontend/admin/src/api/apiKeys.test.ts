import { afterEach, describe, expect, it, vi } from "vitest";

import { createAccountApiKey, listAccountApiKeys, revokeAccountApiKey } from "./apiKeys";

function response(payload: unknown) {
  return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("account API key transport", () => {
  it("lists for self without attaching project state", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ keys: [] }));
    vi.stubGlobal("fetch", fetch);
    expect(await listAccountApiKeys()).toEqual([]);
    expect(fetch).toHaveBeenCalledWith("/api/v1/api-keys", { credentials: "include" });
  });

  it("encodes the owner and key id without putting a secret in a URL", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(response({ keys: [], ok: true })));
    vi.stubGlobal("fetch", fetch);
    await listAccountApiKeys("user/name");
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/api-keys?user_id=user%2Fname");
    await revokeAccountApiKey("key/name");
    expect(fetch.mock.calls[1]).toEqual(["/api/v1/api-keys/key%2Fname", { method: "DELETE", credentials: "include" }]);
  });

  it("sends explicit null expiry and returns the one-time secret", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ key_id: "key-1", key: "test-only-one-time-secret" }));
    vi.stubGlobal("fetch", fetch);
    const result = await createAccountApiKey({ label: "合作服務", expires_at: null });
    expect(result.key).toBe("test-only-one-time-secret");
    expect(fetch).toHaveBeenCalledWith("/api/v1/api-keys", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: "合作服務", expires_at: null }),
    });
  });
});
