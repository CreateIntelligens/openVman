import type { DragEvent } from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeCommitJob } from "../api";

const api = vi.hoisted(() => ({
  commitRawKnowledge: vi.fn(),
  discardRawPending: vi.fn(),
  fetchRawPending: vi.fn(),
  getCommitStatus: vi.fn(),
  uploadRawKnowledgeDocuments: vi.fn(),
}));

vi.mock("../api", () => api);

import { useKnowledgeImport, type ImportItem } from "./useKnowledgeImport";

const POLL_MS = 2000;
const MB = 1024 * 1024;

function job(overrides: Partial<KnowledgeCommitJob> = {}): KnowledgeCommitJob {
  return {
    state: "running",
    started_at: "2026-11-05T10:00:00",
    finished_at: null,
    files: {},
    committed: [],
    skipped: [],
    results: {},
    skip_reasons: {},
    error: null,
    ...overrides,
  };
}

const IDLE_JOB = job({ state: "idle", started_at: null });

function file(name: string, size = 10): File {
  const created = new File(["x"], name);
  Object.defineProperty(created, "size", { value: size });
  return created;
}

const callbacks = {
  loadDocuments: vi.fn(async () => undefined),
  fetchQaTree: vi.fn(async () => []),
  onError: vi.fn(),
  onDropStarted: vi.fn(),
};

interface HookProps {
  projectId?: string;
  currentDir?: string;
  directories?: string[];
  maxFileBytes?: number;
}

function renderImport(initialProps: HookProps = {}) {
  return renderHook(
    (props: HookProps) => useKnowledgeImport({
      projectId: "proj-a",
      currentDir: "knowledge",
      directories: [],
      maxFileBytes: 100 * MB,
      ...callbacks,
      ...props,
    }),
    { initialProps },
  );
}

const flush = () => act(async () => {
  await vi.advanceTimersByTimeAsync(0);
});
const nextPoll = (times = 1) => act(async () => {
  await vi.advanceTimersByTimeAsync(POLL_MS * times);
});

function uploaded(...paths: string[]) {
  api.uploadRawKnowledgeDocuments.mockResolvedValueOnce({
    status: "ok",
    files: paths.map((path) => ({ path })),
  });
}

function started(files: KnowledgeCommitJob["files"]) {
  api.commitRawKnowledge.mockResolvedValueOnce({
    status: "started",
    project_id: "proj-a",
    job: job({ files }),
  });
}

function rowOf(items: ImportItem[], name: string): ImportItem {
  const row = items.find((item) => item.name === name);
  if (!row) throw new Error(`no row named ${name}`);
  return row;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  sessionStorage.clear();
  api.fetchRawPending.mockReset().mockResolvedValue({ files: [] });
  api.getCommitStatus.mockReset().mockResolvedValue(IDLE_JOB);
  api.commitRawKnowledge.mockReset();
  api.uploadRawKnowledgeDocuments.mockReset();
  api.discardRawPending.mockReset().mockResolvedValue({ status: "ok" });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useKnowledgeImport", () => {
  it("shows each file's state from upload to the final result", async () => {
    let finishUpload: (value: unknown) => void = () => {};
    api.uploadRawKnowledgeDocuments.mockReturnValueOnce(new Promise((resolve) => {
      finishUpload = resolve;
    }));
    started({ "guide.md": "pending", "faq.csv": "pending" });
    const { result } = renderImport();
    await flush();

    act(() => result.current.startFiles([file("guide.md", 30), file("faq.csv")]));
    expect(result.current.items.map((item) => [item.name, item.state, item.size])).toEqual([
      ["guide.md", "uploading", 30],
      ["faq.csv", "uploading", 10],
    ]);
    expect(result.current.progress).toEqual({ done: 0, total: 2 });
    expect(api.commitRawKnowledge).not.toHaveBeenCalled();

    await act(async () => {
      finishUpload({ status: "ok", files: [{ path: "raw/guide.md" }, { path: "raw/faq.csv" }] });
      await vi.advanceTimersByTimeAsync(0);
    });
    // 只送這批上傳的檔案，舊檔不會被順手帶入；帶不帶 raw/ 由後端的鍵決定。
    expect(api.commitRawKnowledge).toHaveBeenCalledWith({
      paths: ["guide.md", "faq.csv"],
      normalize: false,
    });
    expect(rowOf(result.current.items, "guide.md").state).toBe("waiting");

    api.getCommitStatus.mockResolvedValueOnce(job({
      files: { "guide.md": "normalizing", "faq.csv": "pending" },
    }));
    await nextPoll();
    expect(rowOf(result.current.items, "guide.md").state).toBe("processing");
    expect(rowOf(result.current.items, "faq.csv").state).toBe("waiting");

    const guideResult = { target: "knowledge/guide.md", kind: "document" as const, language: "zh" as const, updated: false };
    api.getCommitStatus.mockResolvedValueOnce(job({
      files: { "guide.md": "committed", "faq.csv": "normalizing" },
      results: { "guide.md": guideResult },
    }));
    await nextPoll();
    expect(rowOf(result.current.items, "guide.md").state).toBe("done");
    expect(rowOf(result.current.items, "guide.md").result).toEqual(guideResult);
    expect(result.current.progress).toEqual({ done: 1, total: 2 });

    const faqResult = {
      target: "knowledge/qa/faq.md",
      kind: "qa" as const,
      language: "en" as const,
      updated: false,
      qa_node_id: "qa_node_1",
      qa_node_label: "faq",
      qa_parent_label: "English",
      question_count: 2,
    };
    callbacks.loadDocuments.mockClear();
    callbacks.fetchQaTree.mockClear();
    api.fetchRawPending.mockClear();
    api.getCommitStatus.mockResolvedValueOnce(job({
      state: "done",
      finished_at: "2026-11-05T10:01:00",
      files: { "guide.md": "committed", "faq.csv": "committed" },
      results: { "guide.md": guideResult, "faq.csv": faqResult },
    }));
    await nextPoll();
    expect(rowOf(result.current.items, "faq.csv").result).toEqual(faqResult);
    expect(result.current.progress).toBeNull();
    expect(callbacks.loadDocuments).toHaveBeenCalledTimes(1);
    expect(callbacks.fetchQaTree).toHaveBeenCalledTimes(1);
    expect(api.fetchRawPending).toHaveBeenCalledTimes(1);

    // 結束之後不再輪詢。
    api.getCommitStatus.mockClear();
    await nextPoll(5);
    expect(api.getCommitStatus).not.toHaveBeenCalled();
  });

  it("keeps the reason of a skipped file while the rest of the batch succeeds", async () => {
    uploaded("raw/a.md", "raw/scan.pdf");
    api.commitRawKnowledge.mockResolvedValueOnce({
      status: "started",
      project_id: "proj-a",
      job: job({
        state: "done",
        files: { "a.md": "committed", "scan.pdf": "skipped" },
        results: { "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: true } },
        skip_reasons: { "scan.pdf": "讀不到文字內容，可能是掃描檔或檔案損毀" },
      }),
    });
    const { result } = renderImport();
    await flush();

    act(() => result.current.startFiles([file("a.md"), file("scan.pdf")]));
    await flush();

    expect(rowOf(result.current.items, "a.md").result?.updated).toBe(true);
    const skipped = rowOf(result.current.items, "scan.pdf");
    expect(skipped.state).toBe("skipped");
    expect(skipped.message).toBe("讀不到文字內容，可能是掃描檔或檔案損毀");
    expect(result.current.progress).toBeNull();
  });

  it("does not list a skipped file twice, in the results and in the waiting list", async () => {
    uploaded("raw/scan.pdf");
    api.commitRawKnowledge.mockResolvedValueOnce({
      status: "started",
      project_id: "proj-a",
      job: job({
        state: "done",
        files: { "scan.pdf": "skipped" },
        skip_reasons: { "scan.pdf": "讀不到文字內容" },
      }),
    });
    const pendingFile = { path: "scan.pdf", size: 10, updated_at: "2026-11-05T10:00:00" };
    const { result } = renderImport();
    await flush();
    api.fetchRawPending.mockResolvedValue({ files: [pendingFile] });

    act(() => result.current.startFiles([file("scan.pdf")]));
    await flush();

    expect(result.current.items).toHaveLength(1);
    expect(result.current.pendingFiles).toEqual([]);

    // 清除結果之後它還在等待匯入，要看得到才移得掉。
    act(() => result.current.clearResults());
    await flush();
    expect(result.current.items).toEqual([]);
    expect(result.current.pendingFiles).toEqual([pendingFile]);
  });

  it("waits for a running import and sends the same files again", async () => {
    uploaded("raw/a.md");
    api.commitRawKnowledge.mockResolvedValueOnce({
      status: "already_running",
      project_id: "proj-a",
      job: job({ started_at: "other", files: { "other.md": "normalizing" } }),
    });
    const { result } = renderImport();
    await flush();

    act(() => result.current.startFiles([file("a.md")]));
    await flush();
    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(1);
    expect(rowOf(result.current.items, "a.md").state).toBe("waiting");

    api.getCommitStatus.mockResolvedValueOnce(job({ started_at: "other", files: { "other.md": "normalizing" } }));
    await nextPoll();
    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(1);

    api.getCommitStatus.mockResolvedValueOnce(job({ started_at: "other", state: "done" }));
    started({ "a.md": "pending" });
    await nextPoll();
    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(2);
    expect(api.commitRawKnowledge.mock.calls[1][0]).toEqual({ paths: ["a.md"], normalize: false });

    api.getCommitStatus.mockResolvedValueOnce(job({
      state: "done",
      files: { "a.md": "committed" },
      results: { "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false } },
    }));
    await nextPoll();
    expect(rowOf(result.current.items, "a.md").state).toBe("done");
  });

  describe("when another tab or person is importing the same file", () => {
    const resultFor = (path: string) => ({
      target: `knowledge/${path}`,
      kind: "document" as const,
      language: "zh" as const,
      updated: false,
    });

    it("follows a file still queued there instead of sending it again", async () => {
      uploaded("raw/a.md");
      api.commitRawKnowledge.mockResolvedValueOnce({
        status: "already_running",
        project_id: "proj-a",
        job: job({ started_at: "other", files: { "a.md": "pending" } }),
      });
      const { result } = renderImport();
      await flush();
      act(() => result.current.startFiles([file("a.md")]));
      await flush();

      api.getCommitStatus.mockResolvedValueOnce(job({ started_at: "other", files: { "a.md": "normalizing" } }));
      await nextPoll();
      expect(rowOf(result.current.items, "a.md").state).toBe("processing");

      callbacks.loadDocuments.mockClear();
      api.getCommitStatus.mockResolvedValueOnce(job({
        started_at: "other",
        state: "done",
        files: { "a.md": "committed" },
        results: { "a.md": resultFor("a.md") },
      }));
      await nextPoll();

      expect(rowOf(result.current.items, "a.md").state).toBe("done");
      expect(api.commitRawKnowledge).toHaveBeenCalledTimes(1);
      expect(callbacks.loadDocuments).toHaveBeenCalled();
    });

    it("sends a file again when that import had already read the older copy", async () => {
      uploaded("raw/a.md");
      api.commitRawKnowledge.mockResolvedValueOnce({
        status: "already_running",
        project_id: "proj-a",
        job: job({ started_at: "other", files: { "a.md": "normalizing" } }),
      });
      const { result } = renderImport();
      await flush();
      act(() => result.current.startFiles([file("a.md")]));
      await flush();

      started({ "a.md": "pending" });
      api.getCommitStatus.mockResolvedValueOnce(job({
        started_at: "other",
        state: "done",
        files: { "a.md": "committed" },
        results: { "a.md": resultFor("a.md") },
      }));
      await nextPoll();

      // 那批結束時的結果是舊版的，這一列要等新版自己的結果。
      expect(api.commitRawKnowledge).toHaveBeenCalledTimes(2);
      expect(api.commitRawKnowledge.mock.calls[1][0].paths).toEqual(["a.md"]);
      expect(rowOf(result.current.items, "a.md").state).toBe("waiting");
    });

    it("only sends again the files that were not queued there", async () => {
      uploaded("raw/a.md", "raw/b.md");
      api.commitRawKnowledge.mockResolvedValueOnce({
        status: "already_running",
        project_id: "proj-a",
        job: job({ started_at: "other", files: { "a.md": "pending" } }),
      });
      const { result } = renderImport();
      await flush();
      act(() => result.current.startFiles([file("a.md"), file("b.md")]));
      await flush();

      started({ "b.md": "pending" });
      api.getCommitStatus.mockResolvedValueOnce(job({
        started_at: "other",
        state: "done",
        files: { "a.md": "committed" },
        results: { "a.md": resultFor("a.md") },
      }));
      await nextPoll();

      expect(rowOf(result.current.items, "a.md").state).toBe("done");
      expect(api.commitRawKnowledge.mock.calls[1][0].paths).toEqual(["b.md"]);
    });

    it("sends a queued file again if that import stopped before reaching it", async () => {
      uploaded("raw/a.md");
      api.commitRawKnowledge.mockResolvedValueOnce({
        status: "already_running",
        project_id: "proj-a",
        job: job({ started_at: "other", files: { "a.md": "pending" } }),
      });
      const { result } = renderImport();
      await flush();
      act(() => result.current.startFiles([file("a.md")]));
      await flush();

      started({ "a.md": "pending" });
      api.getCommitStatus.mockResolvedValueOnce(job({
        started_at: "other",
        state: "failed",
        files: { "a.md": "pending" },
        error: "匯入中斷",
      }));
      await nextPoll();

      expect(api.commitRawKnowledge).toHaveBeenCalledTimes(2);
    });
  });

  it("stops polling and forgets the rows when the project changes", async () => {
    uploaded("raw/a.md");
    started({ "a.md": "pending" });
    api.getCommitStatus.mockResolvedValue(IDLE_JOB);
    const { result, rerender } = renderImport({ projectId: "proj-a" });
    await flush();
    act(() => result.current.startFiles([file("a.md")]));
    await flush();
    expect(result.current.items).toHaveLength(1);

    api.getCommitStatus.mockClear();
    rerender({ projectId: "proj-b" });
    expect(result.current.items).toEqual([]);
    await flush();
    // 切換時會查一次新專案有沒有匯入在跑；舊專案的輪詢要停掉。
    expect(api.getCommitStatus).toHaveBeenCalledTimes(1);

    callbacks.loadDocuments.mockClear();
    await nextPoll(5);
    expect(api.getCommitStatus).toHaveBeenCalledTimes(1);
    expect(result.current.items).toEqual([]);
    expect(callbacks.loadDocuments).not.toHaveBeenCalled();
  });

  it("does not send an old project's files to the new project", async () => {
    let finishUpload: (value: unknown) => void = () => {};
    api.uploadRawKnowledgeDocuments.mockReturnValueOnce(new Promise((resolve) => {
      finishUpload = resolve;
    }));
    const { result, rerender } = renderImport({ projectId: "proj-a" });
    await flush();
    act(() => result.current.startFiles([file("a.md")]));

    rerender({ projectId: "proj-b" });
    await flush();
    await act(async () => {
      finishUpload({ status: "ok", files: [{ path: "raw/a.md" }] });
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(api.commitRawKnowledge).not.toHaveBeenCalled();
    expect(result.current.items).toEqual([]);
  });

  it("does not start a queued batch in the new project after switching", async () => {
    uploaded("raw/a.md");
    started({ "a.md": "pending" });
    const { result, rerender } = renderImport({ projectId: "proj-a" });
    await flush();
    act(() => result.current.startFiles([file("a.md")]));
    await flush();
    uploaded("raw/b.md");
    act(() => result.current.startFiles([file("b.md")]));
    await flush();
    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(1);

    rerender({ projectId: "proj-b" });
    await nextPoll(3);

    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(1);
  });

  it("stops polling when the page goes away", async () => {
    uploaded("raw/a.md");
    started({ "a.md": "pending" });
    const { result, unmount } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    api.getCommitStatus.mockClear();
    unmount();
    await nextPoll(5);

    expect(api.getCommitStatus).not.toHaveBeenCalled();
  });

  it("keeps the upload error on the row and never commits", async () => {
    api.uploadRawKnowledgeDocuments.mockRejectedValueOnce(new Error("連不上伺服器，請確認網路，或稍等一下再試。"));
    const { result } = renderImport();
    await flush();

    act(() => result.current.startFiles([file("a.md"), file("b.md")]));
    await flush();

    expect(result.current.items.map((item) => [item.state, item.message])).toEqual([
      ["failed", "連不上伺服器，請確認網路，或稍等一下再試。"],
      ["failed", "連不上伺服器，請確認網路，或稍等一下再試。"],
    ]);
    expect(api.commitRawKnowledge).not.toHaveBeenCalled();
    expect(result.current.progress).toBeNull();
  });

  it("lists what a failed upload already saved on the server", async () => {
    const saved = { path: "a.md", size: 10, updated_at: "2026-11-05T10:00:00" };
    api.uploadRawKnowledgeDocuments.mockRejectedValueOnce(new Error("不支援的文件格式"));
    const { result } = renderImport();
    await flush();
    api.fetchRawPending.mockResolvedValue({ files: [saved] });

    act(() => result.current.startFiles([file("a.md"), file("b.md")]));
    await flush();

    expect(result.current.pendingFiles).toEqual([saved]);
  });

  it("marks the batch failed when starting the import fails, and refreshes the waiting list", async () => {
    uploaded("raw/a.md");
    api.commitRawKnowledge.mockRejectedValueOnce(new Error("伺服器出錯了"));
    const { result } = renderImport();
    await flush();
    api.fetchRawPending.mockClear();

    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    const row = rowOf(result.current.items, "a.md");
    expect(row.state).toBe("failed");
    expect(row.message).toBe("伺服器出錯了");
    expect(row.rawPath).toBe("a.md");
    expect(api.fetchRawPending).toHaveBeenCalled();
  });

  it("says the files are gone when the server has nothing to commit", async () => {
    uploaded("raw/a.md");
    api.commitRawKnowledge.mockResolvedValueOnce({ status: "nothing_to_commit", project_id: "proj-a" });
    const { result } = renderImport();
    await flush();

    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    const row = rowOf(result.current.items, "a.md");
    expect(row.state).toBe("skipped");
    expect(row.message).toContain("找不到");
  });

  it("keeps finished rows and writes the job error on the rest when the job fails", async () => {
    uploaded("raw/a.md", "raw/b.md");
    started({ "a.md": "pending", "b.md": "pending" });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md"), file("b.md")]));
    await flush();

    api.getCommitStatus.mockResolvedValueOnce(job({
      state: "failed",
      files: { "a.md": "committed", "b.md": "pending" },
      results: { "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false } },
      error: "匯入中斷，還沒處理的檔案都留著，可以再試一次",
    }));
    await nextPoll();

    expect(rowOf(result.current.items, "a.md").state).toBe("done");
    const unfinished = rowOf(result.current.items, "b.md");
    expect(unfinished.state).toBe("failed");
    expect(unfinished.message).toBe("匯入中斷，還沒處理的檔案都留著，可以再試一次");
  });

  it("treats a service restart as an interruption instead of polling forever", async () => {
    uploaded("raw/a.md");
    started({ "a.md": "pending" });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    // 重啟後 job 只在記憶體裡的進度不見了，查到的是 idle。
    api.getCommitStatus.mockResolvedValueOnce(IDLE_JOB);
    await nextPoll();

    const row = rowOf(result.current.items, "a.md");
    expect(row.state).toBe("failed");
    expect(row.message).toContain("中斷");
    api.getCommitStatus.mockClear();
    await nextPoll(3);
    expect(api.getCommitStatus).not.toHaveBeenCalled();
  });

  it("keeps polling through a short outage", async () => {
    uploaded("raw/a.md");
    started({ "a.md": "pending" });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    api.getCommitStatus.mockRejectedValueOnce(new Error("502"));
    api.getCommitStatus.mockRejectedValueOnce(new Error("502"));
    await nextPoll(2);
    expect(rowOf(result.current.items, "a.md").state).toBe("waiting");

    api.getCommitStatus.mockResolvedValueOnce(job({
      state: "done",
      files: { "a.md": "committed" },
      results: { "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false } },
    }));
    await nextPoll();
    expect(rowOf(result.current.items, "a.md").state).toBe("done");
  });

  it("gives up with a plain message after a long outage", async () => {
    uploaded("raw/a.md");
    started({ "a.md": "pending" });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    api.getCommitStatus.mockRejectedValue(new Error("502"));
    await nextPoll(30);

    const row = rowOf(result.current.items, "a.md");
    expect(row.state).toBe("failed");
    expect(row.message).toContain("連不上伺服器");
  });

  it("refreshes the tree as soon as a file finishes, so its row can be used mid-batch", async () => {
    uploaded("raw/a.csv", "raw/b.md");
    started({ "a.csv": "pending", "b.md": "pending" });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.csv"), file("b.md")]));
    await flush();
    callbacks.fetchQaTree.mockClear();

    api.getCommitStatus.mockResolvedValueOnce(job({
      files: { "a.csv": "committed", "b.md": "normalizing" },
      results: {
        "a.csv": { target: "knowledge/qa/a.md", kind: "qa", language: "zh", updated: false, qa_node_id: "n1" },
      },
    }));
    await nextPoll();
    expect(callbacks.fetchQaTree).toHaveBeenCalledTimes(1);

    // 沒有新結果就不重抓。
    api.getCommitStatus.mockResolvedValueOnce(job({
      files: { "a.csv": "committed", "b.md": "normalizing" },
      results: {
        "a.csv": { target: "knowledge/qa/a.md", kind: "qa", language: "zh", updated: false, qa_node_id: "n1" },
      },
    }));
    await nextPoll();
    expect(callbacks.fetchQaTree).toHaveBeenCalledTimes(1);
  });

  it("rejects unsupported and oversized files on their own rows and uploads the rest", async () => {
    uploaded("raw/ok.md");
    started({ "ok.md": "pending" });
    const { result } = renderImport({ maxFileBytes: 1 * MB });
    await flush();

    act(() => result.current.startFiles([
      file("slides.pptx"),
      file("big.pdf", 2 * MB),
      file("ok.md"),
    ]));
    await flush();

    const slides = rowOf(result.current.items, "slides.pptx");
    expect(slides.state).toBe("skipped");
    expect(slides.message).toContain("格式不能匯入");
    const big = rowOf(result.current.items, "big.pdf");
    expect(big.state).toBe("skipped");
    expect(big.message).toContain("1 MB");
    const [entries, targetDir] = api.uploadRawKnowledgeDocuments.mock.calls[0];
    expect(entries.map((entry: { file: File }) => entry.file.name)).toEqual(["ok.md"]);
    expect(targetDir).toBe("raw");
    expect(api.commitRawKnowledge.mock.calls[0][0].paths).toEqual(["ok.md"]);
  });

  it("does nothing on the server when no file in the batch can be imported", async () => {
    const { result } = renderImport();
    await flush();

    act(() => result.current.startFiles([file("slides.pptx")]));
    await flush();

    expect(api.uploadRawKnowledgeDocuments).not.toHaveBeenCalled();
    expect(result.current.progress).toBeNull();
    expect(rowOf(result.current.items, "slides.pptx").state).toBe("skipped");
  });

  it("ignores the files an operating system leaves in a folder", async () => {
    const { result } = renderImport();
    await flush();

    act(() => result.current.startFiles([file(".DS_Store"), file("Thumbs.db")]));
    await flush();

    expect(result.current.items).toEqual([]);
  });

  it("runs a second batch only after the first one finishes", async () => {
    uploaded("raw/a.md");
    started({ "a.md": "pending" });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    uploaded("raw/b.md");
    act(() => result.current.startFiles([file("b.md")]));
    await flush();
    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(1);
    // 兩批算同一輪，分母不會在第一批結束時跳掉。
    expect(result.current.progress).toEqual({ done: 0, total: 2 });

    started({ "b.md": "pending" });
    api.getCommitStatus.mockResolvedValueOnce(job({
      state: "done",
      files: { "a.md": "committed" },
      results: { "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false } },
    }));
    await nextPoll();

    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(2);
    expect(api.commitRawKnowledge.mock.calls[1][0].paths).toEqual(["b.md"]);
    expect(result.current.progress).toEqual({ done: 1, total: 2 });
  });

  it("lets a newer copy take over a file that is still queued", async () => {
    uploaded("raw/a.md", "raw/b.md");
    started({ "a.md": "pending", "b.md": "pending" });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md"), file("b.md")]));
    await flush();

    // 後端輪到 b.md 時讀到的就是新版，不能再送一批，否則那批會說找不到檔案。
    uploaded("raw/b.md");
    act(() => result.current.startFiles([file("b.md")]));
    await flush();

    expect(result.current.items.filter((item) => item.name === "b.md")).toHaveLength(1);
    api.getCommitStatus.mockResolvedValueOnce(job({
      state: "done",
      files: { "a.md": "committed", "b.md": "committed" },
      results: {
        "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false },
        "b.md": { target: "knowledge/b.md", kind: "document", language: "zh", updated: false },
      },
    }));
    await nextPoll();

    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(1);
    expect(rowOf(result.current.items, "b.md").state).toBe("done");
  });

  it("imports only what the waiting list shows, with the current checkbox", async () => {
    const waiting = [
      { path: "old.md", size: 5, updated_at: "2026-11-01T10:00:00" },
      { path: "folder/old.csv", size: 6, updated_at: "2026-11-01T10:00:00" },
    ];
    api.fetchRawPending.mockResolvedValue({ files: waiting });
    const { result } = renderImport();
    await flush();
    expect(result.current.pendingFiles).toEqual(waiting);

    api.fetchRawPending.mockResolvedValue({ files: [] });
    started({ "old.md": "pending", "folder/old.csv": "pending" });
    act(() => result.current.setSkipNormalize(false));
    act(() => result.current.importPending());
    await flush();

    expect(api.uploadRawKnowledgeDocuments).not.toHaveBeenCalled();
    expect(api.commitRawKnowledge).toHaveBeenCalledWith({
      paths: ["old.md", "folder/old.csv"],
      normalize: true,
    });
    expect(result.current.items.map((item) => item.name)).toEqual(["old.md", "folder/old.csv"]);
    expect(result.current.pendingFiles).toEqual([]);
    expect(result.current.skipNormalize).toBe(true);
  });

  it("lists a new copy of a file that was already imported", async () => {
    uploaded("raw/a.md");
    api.commitRawKnowledge.mockResolvedValueOnce({
      status: "started",
      project_id: "proj-a",
      job: job({
        state: "done",
        files: { "a.md": "committed" },
        results: { "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false } },
      }),
    });
    const newCopy = { path: "a.md", size: 12, updated_at: "2026-11-05T10:05:00" };
    const { result } = renderImport();
    await flush();
    api.fetchRawPending.mockResolvedValue({ files: [newCopy] });

    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    // 匯入途中又傳了新版時，舊的那一列是成功的，新版要看得到才能再匯入。
    expect(rowOf(result.current.items, "a.md").state).toBe("done");
    expect(result.current.pendingFiles).toEqual([newCopy]);
  });

  it("removes a waiting file and refreshes the list", async () => {
    api.fetchRawPending.mockResolvedValueOnce({
      files: [{ path: "old.md", size: 5, updated_at: "2026-11-01T10:00:00" }],
    });
    const { result } = renderImport();
    await flush();
    expect(result.current.pendingFiles).toHaveLength(1);

    api.fetchRawPending.mockResolvedValue({ files: [] });
    await act(async () => {
      await result.current.discardPending("old.md");
    });

    expect(api.discardRawPending).toHaveBeenCalledWith("old.md");
    expect(result.current.pendingFiles).toEqual([]);
    expect(callbacks.onError).not.toHaveBeenCalled();
  });

  it("reports why a waiting file could not be removed", async () => {
    api.discardRawPending.mockRejectedValueOnce(new Error("這個檔案正在匯入，等匯入結束再移除"));
    const { result } = renderImport();
    await flush();

    await act(async () => {
      await result.current.discardPending("old.md");
    });

    expect(callbacks.onError).toHaveBeenCalledWith("這個檔案正在匯入，等匯入結束再移除");
  });

  it("sends the checkbox and the chosen folder with the upload", async () => {
    uploaded("raw/gear/a.md");
    started({ "gear/a.md": "pending" });
    const { result } = renderImport({ directories: ["knowledge/gear"] });
    await flush();

    act(() => result.current.setSkipNormalize(false));
    act(() => result.current.setTargetDir("knowledge/gear"));
    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    expect(api.uploadRawKnowledgeDocuments.mock.calls[0][1]).toBe("raw/gear");
    expect(api.commitRawKnowledge).toHaveBeenCalledWith({ paths: ["gear/a.md"], normalize: true });
    expect(rowOf(result.current.items, "a.md").normalize).toBe(true);
  });

  // AI 整理會改動內容：選了之後一直留著的話，下一批文件也會被改。
  it("goes back to putting files in directly once a batch has started", async () => {
    uploaded("raw/a.md");
    started({ "a.md": "pending" });
    const { result } = renderImport();
    await flush();

    act(() => result.current.setSkipNormalize(false));
    act(() => result.current.startFiles([file("a.md")]));
    await flush();

    expect(api.commitRawKnowledge).toHaveBeenCalledWith({ paths: ["a.md"], normalize: true });
    expect(result.current.skipNormalize).toBe(true);
  });

  it("offers the top level and real folders, never the folder QA tables live in", async () => {
    const { result } = renderImport({
      directories: ["knowledge/gear", "knowledge/gear/rods", "knowledge/qa", "knowledge/qa/old"],
    });
    await flush();

    expect(result.current.targetOptions).toEqual([
      { value: "knowledge", label: "文件（最上層）" },
      { value: "knowledge/gear", label: "gear" },
      { value: "knowledge/gear/rods", label: "gear › rods" },
    ]);
  });

  it("defaults to the current folder and falls back to the top level", async () => {
    const directories = ["knowledge/gear", "knowledge/rods", "knowledge/qa"];
    const { result, rerender } = renderImport({ currentDir: "knowledge/gear", directories });
    await flush();
    expect(result.current.targetDir).toBe("knowledge/gear");
    expect(result.current.targetLabel).toBe("gear");

    // 開著問答文件時目前資料夾是 knowledge/qa，那裡不能選。
    rerender({ currentDir: "knowledge/qa", directories });
    expect(result.current.targetDir).toBe("knowledge");
    expect(result.current.targetLabel).toBe("文件（最上層）");

    // 自己挑過就照挑的，換了目前資料夾才跟著走。
    rerender({ currentDir: "knowledge/gear", directories });
    act(() => result.current.setTargetDir("knowledge/rods"));
    expect(result.current.targetDir).toBe("knowledge/rods");
    rerender({ currentDir: "knowledge", directories });
    expect(result.current.targetDir).toBe("knowledge");
  });

  it("retries a file that was not imported", async () => {
    uploaded("raw/a.md");
    api.commitRawKnowledge.mockResolvedValueOnce({
      status: "started",
      project_id: "proj-a",
      job: job({
        state: "done",
        files: { "a.md": "skipped" },
        skip_reasons: { "a.md": "處理這個檔案時發生錯誤，可以再試一次" },
      }),
    });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md")]));
    await flush();
    const rowId = rowOf(result.current.items, "a.md").id;

    started({ "a.md": "pending" });
    act(() => result.current.retryItem(rowId));
    expect(rowOf(result.current.items, "a.md").state).toBe("waiting");
    expect(rowOf(result.current.items, "a.md").message).toBeUndefined();
    await flush();

    expect(api.commitRawKnowledge).toHaveBeenCalledTimes(2);
    expect(api.commitRawKnowledge.mock.calls[1][0].paths).toEqual(["a.md"]);
    expect(result.current.items).toHaveLength(1);
  });

  it("keeps rows that are still running when the results are cleared", async () => {
    uploaded("raw/a.md", "raw/b.md");
    started({ "a.md": "pending", "b.md": "pending" });
    const { result } = renderImport();
    await flush();
    act(() => result.current.startFiles([file("a.md"), file("b.md")]));
    await flush();
    api.getCommitStatus.mockResolvedValueOnce(job({
      files: { "a.md": "committed", "b.md": "normalizing" },
      results: { "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false } },
    }));
    await nextPoll();

    act(() => result.current.clearResults());

    expect(result.current.items.map((item) => item.name)).toEqual(["b.md"]);
  });

  describe("coming back to the page", () => {
    function storeRows(projectId: string, rows: ImportItem[]) {
      sessionStorage.setItem(`kb-import-items::${projectId}`, JSON.stringify(rows));
    }

    const doneRow: ImportItem = {
      id: "old-1",
      name: "old.md",
      state: "done",
      rawPath: "old.md",
      normalize: true,
      run: 1,
      result: { target: "knowledge/old.md", kind: "document", language: "zh", updated: false },
    };

    it("still shows the results that were not cleared", async () => {
      storeRows("proj-a", [doneRow]);

      const { result } = renderImport();
      await flush();

      expect(result.current.items).toEqual([doneRow]);
      expect(result.current.progress).toBeNull();
    });

    it("keeps each project's results apart", async () => {
      storeRows("proj-a", [doneRow]);

      const { result, rerender } = renderImport({ projectId: "proj-b" });
      await flush();
      expect(result.current.items).toEqual([]);

      rerender({ projectId: "proj-a" });
      await flush();
      expect(result.current.items).toEqual([doneRow]);
    });

    it("picks up the import that is still running", async () => {
      storeRows("proj-a", [{ ...doneRow, id: "a", name: "a.md", rawPath: "a.md", state: "processing", result: undefined }]);
      api.getCommitStatus.mockResolvedValueOnce(job({
        files: { "a.md": "normalizing", "b.md": "pending" },
      }));

      const { result } = renderImport();
      await flush();

      expect(result.current.items.map((item) => [item.name, item.state])).toEqual([
        ["a.md", "processing"],
        ["b.md", "waiting"],
      ]);
      expect(result.current.progress).toEqual({ done: 0, total: 2 });
      // 接手就好，不會再送一次。
      expect(api.commitRawKnowledge).not.toHaveBeenCalled();

      api.getCommitStatus.mockResolvedValueOnce(job({
        state: "done",
        files: { "a.md": "committed", "b.md": "committed" },
        results: {
          "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false },
          "b.md": { target: "knowledge/b.md", kind: "document", language: "en", updated: false },
        },
      }));
      await nextPoll();
      expect(rowOf(result.current.items, "b.md").state).toBe("done");
      expect(result.current.progress).toBeNull();
    });

    it("fills in the result of an import that finished while away", async () => {
      storeRows("proj-a", [
        { ...doneRow, id: "a", name: "a.md", rawPath: "a.md", state: "processing", result: undefined },
        { ...doneRow, id: "b", name: "b.md", rawPath: "b.md", state: "waiting", result: undefined },
      ]);
      api.getCommitStatus.mockResolvedValueOnce(job({
        state: "done",
        files: { "a.md": "committed", "b.md": "skipped" },
        results: { "a.md": { target: "knowledge/a.md", kind: "document", language: "zh", updated: false } },
        skip_reasons: { "b.md": "讀不到文字內容" },
      }));

      const { result } = renderImport();
      await flush();

      expect(rowOf(result.current.items, "a.md").state).toBe("done");
      const skipped = rowOf(result.current.items, "b.md");
      expect(skipped.state).toBe("skipped");
      expect(skipped.message).toBe("讀不到文字內容");
      expect(callbacks.loadDocuments).toHaveBeenCalled();
    });

    it("does not leave rows spinning when nothing is running any more", async () => {
      storeRows("proj-a", [
        { ...doneRow, id: "a", name: "a.md", rawPath: "a.md", state: "waiting", result: undefined },
        { ...doneRow, id: "b", name: "b.md", rawPath: undefined, state: "uploading", result: undefined },
      ]);

      const { result } = renderImport();
      await flush();

      const waiting = rowOf(result.current.items, "a.md");
      expect(waiting.state).toBe("failed");
      expect(waiting.message).toContain("可以再試一次");
      const uploading = rowOf(result.current.items, "b.md");
      expect(uploading.state).toBe("failed");
      expect(uploading.message).toContain("再上傳一次");
      expect(result.current.progress).toBeNull();
    });

    it.each([
      ["nothing is running", IDLE_JOB],
      ["someone else's import is running", job({ started_at: "other", files: { "other.md": "pending" } })],
    ])("does not mistake a file dropped right after opening for a leftover row when %s", async (_name, status) => {
      storeRows("proj-a", [
        { ...doneRow, id: "old", name: "old.md", state: "waiting", result: undefined },
      ]);
      let finishStatus: (value: KnowledgeCommitJob) => void = () => {};
      api.getCommitStatus.mockReturnValueOnce(new Promise((resolve) => {
        finishStatus = resolve;
      }));
      let finishUpload: (value: unknown) => void = () => {};
      api.uploadRawKnowledgeDocuments.mockReturnValueOnce(new Promise((resolve) => {
        finishUpload = resolve;
      }));
      const { result } = renderImport();
      act(() => result.current.startFiles([file("a.md")]));

      await act(async () => {
        finishStatus(status);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(rowOf(result.current.items, "a.md").state).toBe("uploading");
      expect(rowOf(result.current.items, "old.md").state).toBe("failed");

      api.getCommitStatus.mockResolvedValue(IDLE_JOB);
      started({ "a.md": "pending" });
      await act(async () => {
        finishUpload({ status: "ok", files: [{ path: "raw/a.md" }] });
        await vi.advanceTimersByTimeAsync(POLL_MS * 3);
      });
      expect(api.commitRawKnowledge).toHaveBeenCalled();
    });

    it("clears the stored rows once the results are cleared", async () => {
      storeRows("proj-a", [doneRow]);
      const { result } = renderImport();
      await flush();

      act(() => result.current.clearResults());

      expect(sessionStorage.getItem("kb-import-items::proj-a")).toBeNull();
    });

    it("ignores stored rows it cannot read", async () => {
      sessionStorage.setItem("kb-import-items::proj-a", "{not json");
      const { result } = renderImport();
      await flush();
      expect(result.current.items).toEqual([]);
    });
  });

  describe("dragging files in", () => {
    function dragEvent(dataTransfer: Partial<DataTransfer>) {
      return { preventDefault: vi.fn(), dataTransfer } as unknown as DragEvent;
    }

    it("counts nested drag events so the overlay does not flicker", async () => {
      const { result } = renderImport();
      await flush();
      const event = dragEvent({ types: ["Files"] });

      act(() => result.current.handleDragEnter(event));
      act(() => result.current.handleDragEnter(event));
      act(() => result.current.handleDragLeave(event));
      expect(result.current.dragOver).toBe(true);

      act(() => result.current.handleDragLeave(event));
      expect(result.current.dragOver).toBe(false);
    });

    it("ignores drags that are not files, such as moving a row in the tree", async () => {
      const { result } = renderImport();
      await flush();
      const event = dragEvent({ types: ["text/plain"] });

      act(() => result.current.handleDragEnter(event));
      expect(result.current.dragOver).toBe(false);
      await act(async () => {
        await result.current.handleDrop(event);
      });
      expect(api.uploadRawKnowledgeDocuments).not.toHaveBeenCalled();
      expect(callbacks.onDropStarted).not.toHaveBeenCalled();
    });

    it("takes the same path as picking files", async () => {
      uploaded("raw/a.md");
      started({ "a.md": "pending" });
      const { result } = renderImport();
      await flush();
      act(() => result.current.handleDragEnter(dragEvent({ types: ["Files"] })));

      await act(async () => {
        await result.current.handleDrop(dragEvent({
          types: ["Files"],
          files: [file("a.md")] as unknown as FileList,
        }));
      });

      expect(result.current.dragOver).toBe(false);
      expect(callbacks.onDropStarted).toHaveBeenCalledTimes(1);
      expect(api.commitRawKnowledge.mock.calls[0][0].paths).toEqual(["a.md"]);
    });

    it("walks a dropped folder and keeps its structure", async () => {
      uploaded("raw/folder/inner/a.md");
      started({ "folder/inner/a.md": "pending" });
      const { result } = renderImport();
      await flush();

      const fileEntry = {
        isFile: true,
        isDirectory: false,
        name: "a.md",
        file: (resolve: (value: File) => void) => resolve(file("a.md")),
      };
      const reader = (children: unknown[]) => {
        let remaining = children;
        return {
          readEntries: (resolve: (value: unknown[]) => void) => {
            resolve(remaining);
            remaining = [];
          },
        };
      };
      const inner = { isFile: false, isDirectory: true, name: "inner", createReader: () => reader([fileEntry]) };
      const folder = { isFile: false, isDirectory: true, name: "folder", createReader: () => reader([inner]) };

      await act(async () => {
        await result.current.handleDrop(dragEvent({
          types: ["Files"],
          items: [{ webkitGetAsEntry: () => folder }] as unknown as DataTransferItemList,
        }));
      });

      const [entries] = api.uploadRawKnowledgeDocuments.mock.calls[0];
      expect(entries[0].relativePath).toBe("folder/inner/a.md");
      expect(result.current.items[0].name).toBe("folder/inner/a.md");
    });

    it("says so when a dropped folder has no files", async () => {
      const { result } = renderImport();
      await flush();
      const folder = {
        isFile: false,
        isDirectory: true,
        name: "empty",
        createReader: () => ({ readEntries: (resolve: (value: unknown[]) => void) => resolve([]) }),
      };

      await act(async () => {
        await result.current.handleDrop(dragEvent({
          types: ["Files"],
          items: [{ webkitGetAsEntry: () => folder }] as unknown as DataTransferItemList,
        }));
      });

      expect(callbacks.onError).toHaveBeenCalledWith("這裡面沒有檔案可以匯入");
      expect(callbacks.onDropStarted).not.toHaveBeenCalled();
    });
  });
});
