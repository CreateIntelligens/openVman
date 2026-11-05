import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchKnowledgeBaseDocumentsMock = vi.fn();
const fetchKnowledgeDocumentMock = vi.fn();
const reindexKnowledgeMock = vi.fn();
let activeProjectId = "fishing";

vi.mock("../api", () => ({
  fetchKnowledgeBaseDocuments: () => fetchKnowledgeBaseDocumentsMock(),
  fetchKnowledgeDocument: (path: string) => fetchKnowledgeDocumentMock(path),
  reindexKnowledge: () => reindexKnowledgeMock(),
}));

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: activeProjectId }),
}));

import { QUICK_QA_TREE_PATH } from "../components/kb/helpers";
import { useKnowledgeBase } from "./useKnowledgeBase";

describe("useKnowledgeBase project selection", () => {
  beforeEach(() => {
    activeProjectId = "fishing";
    window.localStorage.clear();
    vi.clearAllMocks();
    fetchKnowledgeBaseDocumentsMock.mockImplementation(async () => (
      activeProjectId === "fishing"
        ? {
            documents: [{
              path: "knowledge/fishing.md",
              name: "fishing.md",
              enabled: true,
              is_indexed: true,
            }],
            directories: ["knowledge"],
          }
        : {
            documents: [{
              path: "knowledge/esg.md",
              name: "esg.md",
              enabled: true,
              is_indexed: true,
            }],
            directories: ["knowledge"],
          }
    ));
    fetchKnowledgeDocumentMock.mockResolvedValue({
      path: "knowledge/fishing.md",
      name: "fishing.md",
      enabled: true,
      is_indexed: true,
      content: "# Fishing",
    });
  });

  it("does not request a stale document after switching projects", async () => {
    window.localStorage.setItem(
      "kb-selected-file-path:fishing",
      "knowledge/fishing.md",
    );
    window.localStorage.setItem(
      "kb-selected-file-path:esg",
      "knowledge/fishing.md",
    );
    const { result, rerender } = renderHook(() => useKnowledgeBase());

    await waitFor(() => {
      expect(fetchKnowledgeDocumentMock).toHaveBeenCalledWith(
        "knowledge/fishing.md",
      );
    });
    fetchKnowledgeDocumentMock.mockClear();

    await act(async () => {
      activeProjectId = "esg";
      rerender();
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.selectedPath).toBe("knowledge");
    });
    expect(fetchKnowledgeDocumentMock).not.toHaveBeenCalled();
    expect(
      window.localStorage.getItem("kb-selected-file-path:esg"),
    ).toBe("knowledge");
    expect(
      window.localStorage.getItem("kb-selected-file-path:fishing"),
    ).toBe("knowledge/fishing.md");
  });

  // 重整後選取會還原，右側面板要跟著回到檔案檢視——只還原選取卻停在資料夾
  // 檢視的話，使用者看到的不是他離開時的畫面。
  it("restores the file pane when the remembered path is a document", async () => {
    window.localStorage.setItem(
      "kb-selected-file-path:fishing",
      "knowledge/fishing.md",
    );

    const { result } = renderHook(() => useKnowledgeBase());

    await waitFor(() => {
      expect(result.current.selectedPath).toBe("knowledge/fishing.md");
      expect(result.current.rightPane).toBe("file");
    });
  });

  it("keeps the folder pane when the remembered path is a directory", async () => {
    window.localStorage.setItem("kb-selected-file-path:fishing", "knowledge");

    const { result } = renderHook(() => useKnowledgeBase());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.rightPane).toBe("folder");
    expect(fetchKnowledgeDocumentMock).not.toHaveBeenCalled();
  });
});

describe("useKnowledgeBase folder selection", () => {
  beforeEach(() => {
    activeProjectId = "fishing";
    window.localStorage.clear();
    vi.clearAllMocks();
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue({
      documents: [{
        path: "knowledge/fishing.md",
        name: "fishing.md",
        enabled: true,
        is_indexed: true,
      }],
      directories: ["knowledge", "knowledge/gear"],
    });
    fetchKnowledgeDocumentMock.mockResolvedValue({
      path: "knowledge/fishing.md",
      name: "fishing.md",
      enabled: true,
      is_indexed: true,
      content: "# Fishing",
    });
  });

  it("expands the quick QA section by default", async () => {
    const { result } = renderHook(() => useKnowledgeBase());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.visibleExpandedDirs.has("knowledge")).toBe(true);
    expect(result.current.visibleExpandedDirs.has(QUICK_QA_TREE_PATH)).toBe(true);
  });

  // 實測：看文件看到一半點資料夾，文件會被關掉，沒存的修改也跟著不見。
  it("only toggles a clicked folder while a document is open", async () => {
    const { result } = renderHook(() => useKnowledgeBase());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      result.current.handleTreeSelect({ type: "file", path: "knowledge/fishing.md" });
    });
    await waitFor(() => expect(result.current.openDocument?.path).toBe("knowledge/fishing.md"));

    act(() => {
      result.current.handleTreeSelect({ type: "folder", path: "knowledge/gear" });
    });

    expect(result.current.visibleExpandedDirs.has("knowledge/gear")).toBe(true);
    expect(result.current.rightPane).toBe("file");
    expect(result.current.openDocument?.path).toBe("knowledge/fishing.md");
    expect(result.current.selectedPath).toBe("knowledge/fishing.md");

    act(() => {
      result.current.handleTreeSelect({ type: "folder", path: "knowledge/gear" });
    });
    expect(result.current.visibleExpandedDirs.has("knowledge/gear")).toBe(false);
  });

  it("keeps a document that is still loading when a folder is clicked", async () => {
    let finishLoading: (document: unknown) => void = () => {};
    fetchKnowledgeDocumentMock.mockReturnValue(new Promise((resolve) => {
      finishLoading = resolve;
    }));
    const { result } = renderHook(() => useKnowledgeBase());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.handleTreeSelect({ type: "file", path: "knowledge/fishing.md" });
    });
    expect(result.current.openDocument).toBeNull();

    act(() => {
      result.current.handleTreeSelect({ type: "folder", path: "knowledge/gear" });
    });
    expect(result.current.rightPane).toBe("file");
    expect(result.current.selectedPath).toBe("knowledge/fishing.md");

    await act(async () => {
      finishLoading({ path: "knowledge/fishing.md", content: "# Fishing" });
    });
    expect(result.current.openDocument?.path).toBe("knowledge/fishing.md");
  });

  it("remembers the clicked folder when no document is open", async () => {
    const { result } = renderHook(() => useKnowledgeBase());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.handleTreeSelect({ type: "folder", path: "knowledge/gear" });
    });

    expect(result.current.visibleExpandedDirs.has("knowledge/gear")).toBe(true);
    expect(result.current.selectedPath).toBe("knowledge/gear");
    expect(result.current.rightPane).toBe("folder");
  });
});

describe("useKnowledgeBase document list", () => {
  beforeEach(() => {
    activeProjectId = "fishing";
    window.localStorage.clear();
    vi.clearAllMocks();
    fetchKnowledgeBaseDocumentsMock.mockReset();
    fetchKnowledgeDocumentMock.mockReset();
  });

  it("is not ready to show the home screen until the last document is being restored", async () => {
    window.localStorage.setItem("kb-selected-file-path:fishing", "knowledge/fishing.md");
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue({
      documents: [{ path: "knowledge/fishing.md", enabled: true, is_indexed: true }],
      directories: [],
    });
    fetchKnowledgeDocumentMock.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useKnowledgeBase());
    expect(result.current.contentReady).toBe(false);
    expect(result.current.documentsLoaded).toBe(false);

    await waitFor(() => expect(result.current.contentReady).toBe(true));
    expect(result.current.documentsLoaded).toBe(true);
    // 同一輪就已經切到文件檢視，首頁不會閃一下。
    expect(result.current.rightPane).toBe("file");
  });

  it("is ready but not loaded when the list could not be fetched", async () => {
    fetchKnowledgeBaseDocumentsMock.mockRejectedValue(new Error("502"));

    const { result } = renderHook(() => useKnowledgeBase());

    await waitFor(() => expect(result.current.contentReady).toBe(true));
    expect(result.current.documentsLoaded).toBe(false);
    expect(result.current.status?.type).toBe("error");
  });

  it("ignores an older response that arrives after a newer one", async () => {
    const stale = { documents: [{ path: "knowledge/deleted.md", enabled: true, is_indexed: true }], directories: [] };
    const fresh = { documents: [{ path: "knowledge/kept.md", enabled: true, is_indexed: true }], directories: [] };
    let finishStale: (value: typeof stale) => void = () => {};
    fetchKnowledgeBaseDocumentsMock
      .mockReturnValueOnce(new Promise((resolve) => { finishStale = resolve; }))
      .mockResolvedValueOnce(fresh);

    const { result } = renderHook(() => useKnowledgeBase());
    await act(async () => {
      await result.current.loadDocuments();
    });
    expect(result.current.documents.map((document) => document.path)).toEqual(["knowledge/kept.md"]);

    await act(async () => {
      finishStale(stale);
    });
    expect(result.current.documents.map((document) => document.path)).toEqual(["knowledge/kept.md"]);
    expect(result.current.loading).toBe(false);
  });

  it("leaves the chosen folder alone when closing the file view with nothing open", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue({ documents: [], directories: ["knowledge/gear"] });
    const { result } = renderHook(() => useKnowledgeBase());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => {
      result.current.handleTreeSelect({ type: "folder", path: "knowledge/gear" });
    });

    act(() => {
      result.current.closeFileView();
    });

    expect(result.current.selectedPath).toBe("knowledge/gear");
    expect(result.current.currentDir).toBe("knowledge/gear");
  });

  it("goes back to the folder of the document and forgets unsaved edits when closing it", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue({
      documents: [{ path: "knowledge/gear/rod.md", enabled: true, is_indexed: true }],
      directories: ["knowledge/gear"],
    });
    fetchKnowledgeDocumentMock.mockResolvedValue({ path: "knowledge/gear/rod.md", content: "# Rod" });
    const { result } = renderHook(() => useKnowledgeBase());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      result.current.handleTreeSelect({ type: "file", path: "knowledge/gear/rod.md" });
    });
    await waitFor(() => expect(result.current.openDocument?.path).toBe("knowledge/gear/rod.md"));
    act(() => result.current.updateEditContent("# changed"));
    expect(result.current.editorDirty).toBe(true);

    act(() => {
      result.current.closeFileView();
    });

    expect(result.current.editorDirty).toBe(false);
    expect(result.current.openDocument).toBeNull();
    expect(result.current.rightPane).toBe("folder");
    expect(result.current.selectedPath).toBe("knowledge/gear");
    expect(result.current.currentDir).toBe("knowledge/gear");
  });

  it("calls the index rebuild by its plain name in the result message", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue({ documents: [], directories: [] });
    reindexKnowledgeMock.mockResolvedValue({ status: "ok", document_count: 3, chunk_count: 42 });
    const { result } = renderHook(() => useKnowledgeBase());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleReindex();
    });

    expect(result.current.status?.message).toBe("已重建搜尋資料：文件 3 份，段落 42 筆。");
    expect(result.current.status?.message).not.toContain("chunk");
  });
});

// 實測：匯入後樹上的狀態一直轉圈，要重新整理頁面才看得到結果。
describe("useKnowledgeBase index status polling", () => {
  const processing = {
    path: "knowledge/new.md",
    updated_at: "2026-11-05T10:00:00",
    enabled: true,
    is_indexable: true,
    is_indexed: false,
  };
  const indexed = { ...processing, is_indexed: true };

  const documentsResponse = (...documents: unknown[]) => ({ documents, directories: [] });

  async function settle() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  async function advance(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  beforeEach(() => {
    vi.useFakeTimers();
    activeProjectId = "fishing";
    window.localStorage.clear();
    vi.clearAllMocks();
    fetchKnowledgeBaseDocumentsMock.mockReset();
    fetchKnowledgeDocumentMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("refreshes until the document is searchable, then stops", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(processing));
    const { result } = renderHook(() => useKnowledgeBase());
    await settle();
    expect(result.current.processingCount).toBe(1);
    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(1);

    await advance(3000);
    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(2);

    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(indexed));
    await advance(4500);
    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(3);
    expect(result.current.processingCount).toBe(0);

    await advance(60_000);
    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(3);
  });

  it("does not poll for disabled documents, they are not processing", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(
      documentsResponse({ ...processing, enabled: false }),
    );
    const { result } = renderHook(() => useKnowledgeBase());
    await settle();
    expect(result.current.processingCount).toBe(0);

    await advance(60_000);

    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(1);
  });

  it("does not poll for documents that can never be searched", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(
      documentsResponse({ ...processing, is_indexable: false }),
    );
    const { result } = renderHook(() => useKnowledgeBase());
    await settle();
    expect(result.current.processingCount).toBe(0);

    await advance(60_000);

    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(1);
  });

  it("stretches the interval up to 15 seconds", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(processing));
    renderHook(() => useKnowledgeBase());
    await settle();

    const callsAfter = async (ms: number) => {
      fetchKnowledgeBaseDocumentsMock.mockClear();
      await advance(ms);
      return fetchKnowledgeBaseDocumentsMock.mock.calls.length;
    };

    expect(await callsAfter(3000)).toBe(1);
    expect(await callsAfter(4499)).toBe(0);
    expect(await callsAfter(1)).toBe(1);
    // 6.75、10.125，之後都是 15 秒。
    expect(await callsAfter(6750 + 10_125)).toBe(2);
    expect(await callsAfter(14_999)).toBe(0);
    expect(await callsAfter(1)).toBe(1);
    expect(await callsAfter(15_000)).toBe(1);
  });

  it("gives up after five minutes without any change, and starts again on the next one", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(processing));
    const { result } = renderHook(() => useKnowledgeBase());
    await settle();

    await advance(5 * 60 * 1000);
    fetchKnowledgeBaseDocumentsMock.mockClear();
    await advance(10 * 60 * 1000);
    expect(fetchKnowledgeBaseDocumentsMock).not.toHaveBeenCalled();

    // 例如存了一份文件：列表重新載入，又有東西可能在變。
    await act(async () => {
      await result.current.loadDocuments();
    });
    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(1);
    await advance(3000);
    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(2);
  });

  it("starts over when another document starts or finishes processing", async () => {
    const other = { ...processing, path: "knowledge/other.md" };
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(processing, other));
    renderHook(() => useKnowledgeBase());
    await settle();
    await advance(3000 + 4500 + 6750);

    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(processing));
    await advance(10_125);
    fetchKnowledgeBaseDocumentsMock.mockClear();

    await advance(3000);
    expect(fetchKnowledgeBaseDocumentsMock).toHaveBeenCalledTimes(1);
  });

  it("does not touch the loading flag or the list when nothing changed, so the tree does not flicker", async () => {
    fetchKnowledgeBaseDocumentsMock.mockImplementation(async () => documentsResponse(processing));
    const { result } = renderHook(() => useKnowledgeBase());
    await settle();
    const before = result.current.documents;
    const treeBefore = result.current.filteredTree;
    const loadingSeen: boolean[] = [];

    let finishRefresh: (value: unknown) => void = () => {};
    fetchKnowledgeBaseDocumentsMock.mockReturnValueOnce(new Promise((resolve) => {
      finishRefresh = resolve;
    }));
    await advance(3000);
    loadingSeen.push(result.current.loading);
    await act(async () => {
      finishRefresh(documentsResponse(processing));
      await vi.advanceTimersByTimeAsync(0);
    });
    loadingSeen.push(result.current.loading);

    expect(loadingSeen).toEqual([false, false]);
    expect(result.current.documents).toBe(before);
    expect(result.current.filteredTree).toBe(treeBefore);
  });

  it("does not pop up an error when a refresh fails, and tries again", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValueOnce(documentsResponse(processing));
    fetchKnowledgeBaseDocumentsMock.mockRejectedValueOnce(new Error("502"));
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(indexed));
    const { result } = renderHook(() => useKnowledgeBase());
    await settle();

    await advance(3000);
    expect(result.current.status).toBeNull();
    expect(result.current.processingCount).toBe(1);

    await advance(4500);
    expect(result.current.processingCount).toBe(0);
  });

  it("keeps a response from before a delete from bringing the document back", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValueOnce(documentsResponse(processing));
    const { result } = renderHook(() => useKnowledgeBase());
    await settle();

    let finishRefresh: (value: unknown) => void = () => {};
    fetchKnowledgeBaseDocumentsMock.mockReturnValueOnce(new Promise((resolve) => {
      finishRefresh = resolve;
    }));
    await advance(3000);

    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse());
    await act(async () => {
      await result.current.loadDocuments();
    });
    await act(async () => {
      finishRefresh(documentsResponse(processing));
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.documents).toEqual([]);
  });

  it("stops when the project changes", async () => {
    fetchKnowledgeBaseDocumentsMock.mockImplementation(async () => (
      activeProjectId === "fishing"
        ? documentsResponse(processing)
        : documentsResponse(indexed)
    ));
    const { rerender } = renderHook(() => useKnowledgeBase());
    await settle();

    activeProjectId = "esg";
    rerender();
    await settle();
    fetchKnowledgeBaseDocumentsMock.mockClear();

    await advance(60_000);
    expect(fetchKnowledgeBaseDocumentsMock).not.toHaveBeenCalled();
  });

  it("stops when the page goes away", async () => {
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(processing));
    const { unmount } = renderHook(() => useKnowledgeBase());
    await settle();
    fetchKnowledgeBaseDocumentsMock.mockClear();

    unmount();
    await advance(60_000);

    expect(fetchKnowledgeBaseDocumentsMock).not.toHaveBeenCalled();
  });

  it("updates the status of the open document without touching what is being edited", async () => {
    window.localStorage.setItem("kb-selected-file-path:fishing", processing.path);
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(processing));
    fetchKnowledgeDocumentMock.mockResolvedValue({ ...processing, content: "# server" });
    const { result } = renderHook(() => useKnowledgeBase());
    await settle();
    expect(result.current.openDocument?.is_indexed).toBe(false);
    act(() => result.current.updateEditContent("# typing"));

    fetchKnowledgeBaseDocumentsMock.mockResolvedValue(documentsResponse(indexed));
    await advance(3000);

    expect(result.current.openDocument?.is_indexed).toBe(true);
    expect(result.current.openDocument?.content).toBe("# server");
    expect(result.current.editContent).toBe("# typing");
    expect(result.current.editorDirty).toBe(true);
  });
});
