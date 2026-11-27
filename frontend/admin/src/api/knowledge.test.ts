import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyRenormalizedKnowledgeDocument,
  commitRawKnowledge,
  createKnowledgeNote,
  DEFAULT_QA_EXPORT_FILENAME,
  discardRawPending,
  fetchQaSyncStatus,
  exportQaExcel,
  fetchRawPending,
  parseContentDispositionFilename,
  previewRenormalizedKnowledgeDocument,
  uploadRawKnowledgeDocuments,
  uploadKnowledgeDocuments,
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
    f.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ document_max_upload_bytes: 1024 }),
    } as Response);
    const file = new File([new Uint8Array([0x50, 0x4b])], "report.docx");

    await uploadRawKnowledgeDocuments(
      [{ file, relativePath: "clinic/report.docx" }],
      "raw/clinic",
    );

    expect(f.mock.calls[0][0]).toBe("/api/v1/uploads/limits");
    const [url, init] = f.mock.calls[1];
    expect(url).toBe("/api/v1/knowledge/raw/upload");
    expect((init as RequestInit).method).toBe("POST");
    const body = (init as RequestInit).body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("target_dir")).toBe("raw/clinic");
    expect((body as FormData).get("project_id")).toBe("default");
  });

  // 實測：採納會連以前留在暫存區的檔案一起處理，所以這批要指名。
  it("commits only the named files and can skip the AI step", async () => {
    const f = mockFetch({ status: "started", project_id: "default" });

    await commitRawKnowledge({ paths: ["a.csv", "clinic/b.docx"], normalize: false });

    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/v1/knowledge/raw/commit");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      project_id: "default",
      paths: ["a.csv", "clinic/b.docx"],
      normalize: false,
    });
  });

  it("leaves paths and normalize to the server when they are not given", async () => {
    const f = mockFetch({ status: "nothing_to_commit", project_id: "default" });

    await commitRawKnowledge();

    expect(JSON.parse((f.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      project_id: "default",
    });
  });

  it("lists the files waiting to be imported", async () => {
    const f = mockFetch({ files: [{ path: "a.csv", size: 3, updated_at: "2026-11-05T10:00:00" }] });

    const response = await fetchRawPending();

    expect(f.mock.calls[0][0]).toBe("/api/v1/knowledge/raw/pending?project_id=default");
    expect(response.files[0].path).toBe("a.csv");
  });

  it("removes one waiting file by its path", async () => {
    const f = mockFetch({ status: "ok" });

    await discardRawPending("clinic/舊檔.csv");

    const [url, init] = f.mock.calls[0];
    expect((init as RequestInit).method).toBe("DELETE");
    const query = new URL(url as string, "http://localhost").searchParams;
    expect(query.get("path")).toBe("clinic/舊檔.csv");
    expect(query.get("project_id")).toBe("default");
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
    expect(url).toBe("/api/v1/knowledge/renormalize/preview");
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
    expect(url).toBe("/api/v1/knowledge/renormalize/apply");
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
    expect(url).toBe("/api/v1/knowledge/note");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      title: "FAQ",
      content: "## Q\n\nA",
      project_id: "default",
      target_dir: "faq",
      note_format: "text",
    });
  });

  it("creates qa-format notes with note_format=qa", async () => {
    const f = mockFetch({
      status: "ok",
      path: "knowledge/qa/FAQ.md",
      size: 10,
      document: { path: "knowledge/qa/FAQ.md" },
    });

    await createKnowledgeNote("FAQ", "## Q\n\nA", "", "qa");

    const [, init] = f.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({
      note_format: "qa",
      target_dir: "",
    });
  });

  it("fetches QA category sync status for the active or given project", async () => {
    const f = mockFetch({
      categories: { returns: "synced", shipping: "updating", billing: "failed" },
    });

    const defaultResult = await fetchQaSyncStatus();
    expect(f.mock.calls[0][0]).toBe("/api/v1/knowledge/qa/sync-status?project_id=default");
    expect(defaultResult).toEqual({
      categories: { returns: "synced", shipping: "updating", billing: "failed" },
    });

    await fetchQaSyncStatus("clinic");
    expect(f.mock.calls[1][0]).toBe("/api/v1/knowledge/qa/sync-status?project_id=clinic");
  });

  it("exports QA Excel with project_id, credentials, and decoded UTF-8 filename", async () => {
    const payload = new Blob(["xlsx-data"], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const f = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => payload,
      headers: new Headers({
        "content-disposition": "attachment; filename*=UTF-8''%E5%BF%AB%E9%80%9F%E5%9B%9E%E8%A6%86_20261120.xlsx",
      }),
    } as Response);

    const result = await exportQaExcel("proj-a");

    expect(f).toHaveBeenCalledWith(
      "/api/v1/knowledge/qa/export?project_id=proj-a",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(result.blob).toBe(payload);
    expect(result.filename).toBe("快速回覆_20261120.xlsx");
  });

  it("falls back to default filename when Content-Disposition is absent or invalid", async () => {
    const payload = new Blob(["xlsx-data"]);
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => payload,
      headers: new Headers(),
    } as Response);

    const result = await exportQaExcel();

    expect(result.filename).toBe(DEFAULT_QA_EXPORT_FILENAME);
    expect(parseContentDispositionFilename("attachment; filename*=UTF-8''%ZZ")).toBe(DEFAULT_QA_EXPORT_FILENAME);
    expect(parseContentDispositionFilename('attachment; filename="qa_backup.xlsx"')).toBe("qa_backup.xlsx");
    expect(parseContentDispositionFilename('attachment; filename="a;b\\"c.xlsx"')).toBe('a;b"c.xlsx');
    expect(parseContentDispositionFilename("attachment; filename=plain_export.xlsx; size=10")).toBe("plain_export.xlsx");
  });

  it("parses an unterminated run of backslashes in linear time", () => {
    // 舊正則每多兩個反斜線耗時約乘 2.7，38 個在 Node 約 1 秒；同步回溯沒辦法被測試 timeout
    // 中斷，所以用有限長度加耗時上限，退回舊寫法時測試會失敗而不是卡住。
    const header = `attachment; filename="${"\\".repeat(38)}`;
    const started = performance.now();
    expect(parseContentDispositionFilename(header)).toBe(DEFAULT_QA_EXPORT_FILENAME);
    expect(performance.now() - started).toBeLessThan(200);
    expect(parseContentDispositionFilename(`attachment; filename="${"\\".repeat(5000)}`)).toBe(
      DEFAULT_QA_EXPORT_FILENAME,
    );
  });

  it("rejects exportQaExcel when the server returns an error status", async () => {
    mockFetch({ detail: "export failed" }, false, 500);

    await expect(exportQaExcel()).rejects.toThrow("export failed");
  });
});


describe.each([uploadKnowledgeDocuments, uploadRawKnowledgeDocuments])(
  "knowledge upload limits: %s",
  (upload) => {
    it("rejects files above the backend limit without uploading", async () => {
      const f = mockFetch({ document_max_upload_bytes: 8 });
      const file = new File(["123456789"], "report.txt");
      await expect(upload([{ file, relativePath: file.name }])).rejects.toThrow(
        "檔案大小不可超過 8 bytes",
      );
      expect(f).toHaveBeenCalledTimes(1);
    });

    it("allows more than 5 MiB when the backend allows it", async () => {
      const f = mockFetch({ document_max_upload_bytes: 6 * 1024 * 1024 });
      const file = new File([new Uint8Array(6 * 1024 * 1024)], "report.txt");
      await upload([{ file, relativePath: file.name }]);
      expect(f).toHaveBeenCalledTimes(2);
      expect(f.mock.calls[1][1]?.method).toBe("POST");
    });

    it("does not upload when fetching limits fails", async () => {
      const f = mockFetch({ error: "unavailable" }, false, 503);
      const file = new File(["small"], "report.txt");
      await expect(upload([{ file, relativePath: file.name }])).rejects.toThrow(
        "unavailable",
      );
      expect(f).toHaveBeenCalledTimes(1);
    });

    it("does not upload when the limit response is invalid", async () => {
      const f = mockFetch({});
      const file = new File(["small"], "report.txt");
      await expect(upload([{ file, relativePath: file.name }])).rejects.toThrow(
        "無法取得檔案大小上限",
      );
      expect(f).toHaveBeenCalledTimes(1);
    });
  },
);
