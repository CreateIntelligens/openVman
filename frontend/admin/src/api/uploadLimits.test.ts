import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_UPLOAD_LIMITS, fetchUploadLimits } from "./uploadLimits";

afterEach(() => vi.restoreAllMocks());

describe("fetchUploadLimits", () => {
  it("reads /uploads/limits and keeps defaults for fields an older backend omits", async () => {
    const f = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ document_max_upload_bytes: 1024, asr_max_upload_bytes: 2048 }),
      headers: new Headers({ "content-type": "application/json" }),
    } as Response);

    const limits = await fetchUploadLimits();

    expect(f.mock.calls[0][0]).toBe("/api/v1/uploads/limits");
    expect(limits.document_max_upload_bytes).toBe(1024);
    expect(limits.asr_max_upload_bytes).toBe(2048);
    expect(limits.avatar_source_max_upload_bytes).toBe(
      DEFAULT_UPLOAD_LIMITS.avatar_source_max_upload_bytes,
    );
  });
});
