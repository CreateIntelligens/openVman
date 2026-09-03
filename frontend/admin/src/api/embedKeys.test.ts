import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createEmbedKey,
  deleteEmbedKey,
  listEmbedKeys,
  parseDelimitedList,
  setEmbedKeyDisabled,
  updateEmbedKey,
} from "./embedKeys";

const KEY_ID = "ovk_aaaaaaaaaaaaaaaaaaaaaaaa";

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as unknown as Response;
}

describe("embedKeys api", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(jsonResponse({ embed_keys: [] }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists keys from the versioned admin path", async () => {
    await listEmbedKeys();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/embed-keys");
  });

  it("posts a create payload as JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ key_id: KEY_ID }));

    await createEmbedKey({
      label: "site",
      project_id: "default",
      allowed_origins: ["https://a.example"],
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/embed-keys");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toMatchObject({
      project_id: "default",
      allowed_origins: ["https://a.example"],
    });
  });

  it("patches a single key by id", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ key_id: KEY_ID }));

    await updateEmbedKey(KEY_ID, { label: "renamed" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/v1/embed-keys/${KEY_ID}`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ label: "renamed" });
  });

  it("toggles disabled through the patch endpoint", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ key_id: KEY_ID }));

    await setEmbedKeyDisabled(KEY_ID, true);

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      disabled: true,
    });
  });

  it("deletes a key by id", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "deleted" }));

    await deleteEmbedKey(KEY_ID);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/v1/embed-keys/${KEY_ID}`);
    expect(init.method).toBe("DELETE");
  });

  it("parses origins from newlines and commas, dropping duplicates", () => {
    expect(
      parseDelimitedList("https://a.example\n https://b.example , https://a.example"),
    ).toEqual(["https://a.example", "https://b.example"]);
    expect(parseDelimitedList("   ")).toEqual([]);
  });
});
