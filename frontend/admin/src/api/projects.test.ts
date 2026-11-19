import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createProject,
  deleteProjectGeminiCredential,
  fetchProjectGeminiCredential,
  saveProjectGeminiCredential,
  setProjectVendor,
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

  it("sends the vendor name when creating a project", async () => {
    await createProject("新專案", "合作廠商");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/projects");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ label: "新專案", vendor_name: "合作廠商" });
  });

  it("can clear a vendor using the encoded project path", async () => {
    await setProjectVendor("project/a", null);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/projects/project%2Fa/vendor");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ vendor_name: null });
  });
});
