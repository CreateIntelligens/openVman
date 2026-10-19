import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteProjectGeminiCredential,
  fetchProjectGeminiCredential,
  saveProjectGeminiCredential,
} from "./projects";

describe("project Gemini credential API", () => {
  const metadata = { project_id: "project/a", source: "shared", configured: true, label: null, masked: null, credential_id: null, updated_at: null };
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset().mockResolvedValue({ ok: true, status: 200, json: async () => metadata });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("reads metadata from the encoded project path", async () => {
    expect(await fetchProjectGeminiCredential("project/a")).toEqual(metadata);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/projects/project%2Fa/gemini-credential");
  });

  it("sends only the label and key in a PUT body", async () => {
    await saveProjectGeminiCredential("project/a", { label: "院方專案", api_key: "test-private-key" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/projects/project%2Fa/gemini-credential");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ label: "院方專案", api_key: "test-private-key" });
  });

  it("uses DELETE without a key payload to return to shared credentials", async () => {
    expect(await deleteProjectGeminiCredential("project/a")).toEqual(metadata);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/projects/project%2Fa/gemini-credential");
    expect(init.method).toBe("DELETE");
    expect(init.body).toBeUndefined();
  });
});
