import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyRenormalizedKnowledgeDocument,
  createKnowledgeNote,
  previewRenormalizedKnowledgeDocument,
  uploadRawKnowledgeDocuments,
} from "./knowledge";

afterEach(() => vi.restoreAllMocks());

function mockFetch(payload: unknown, ok = true, status = 200) {
  return vi.spyOn(global, "fetch").mockResolvedValue({
    ok,
    status,
    json: async () => payload,
    headers: new Headers({ "content-type": "application/json" }),
  } as Response);
}

describe("knowledge api", () => {
  it("uploads files to the raw staging endpoint", async () => {
    const f = mockFetch({ status: "ok", files: [{ path: "raw/clinic/report.docx" }] });
    const file = new File([new Uint8Array([0x50, 0x4b])], "report.docx");

    await uploadRawKnowledgeDocuments(
      [{ file, relativePath: "clinic/report.docx" }],
      "raw/clinic",
    );

    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/knowledge/raw/upload");
    expect((init as RequestInit).method).toBe("POST");
    const body = (init as RequestInit).body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("target_dir")).toBe("raw/clinic");
    expect((body as FormData).get("project_id")).toBe("default");
  });

  it("requests a normalization preview without overwriting the document", async () => {
    const f = mockFetch({
      status: "ok",
      project_id: "default",
      path: "knowledge/ocr.md",
      content: "# Clean",
      size: 7,
    });

    await previewRenormalizedKnowledgeDocument("knowledge/ocr.md");

    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/knowledge/renormalize/preview");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      path: "knowledge/ocr.md",
      project_id: "default",
    });
  });

  it("applies previewed normalization content", async () => {
    const f = mockFetch({
      status: "ok",
      project_id: "default",
      document: { path: "knowledge/ocr.md", backup_path: ".normalization-backups/x" },
    });

    await applyRenormalizedKnowledgeDocument("knowledge/ocr.md", "# Clean");

    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/knowledge/renormalize/apply");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      path: "knowledge/ocr.md",
      content: "# Clean",
      project_id: "default",
    });
  });

  it("sends target_dir when creating a note in a knowledge directory", async () => {
    const f = mockFetch({
      status: "ok",
      path: "knowledge/faq/FAQ.md",
      size: 12,
      document: { path: "knowledge/faq/FAQ.md" },
    });

    await createKnowledgeNote("FAQ", "## Q\n\nA", "faq");

    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/knowledge/note");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      title: "FAQ",
      content: "## Q\n\nA",
      project_id: "default",
      target_dir: "faq",
    });
  });
});
