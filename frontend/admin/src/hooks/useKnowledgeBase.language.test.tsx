import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeDocumentSummary } from "../api";

const fetchKnowledgeBaseDocumentsMock = vi.fn();
const fetchKnowledgeDocumentMock = vi.fn();
const updateKnowledgeDocumentMetaMock = vi.fn();
let activeProjectId = "fishing";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchKnowledgeBaseDocuments: () => fetchKnowledgeBaseDocumentsMock(),
    fetchKnowledgeDocument: (path: string) => fetchKnowledgeDocumentMock(path),
    updateKnowledgeDocumentMeta: (path: string, meta: unknown) => updateKnowledgeDocumentMetaMock(path, meta),
  };
});

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: activeProjectId }),
}));

import { useKnowledgeBase } from "./useKnowledgeBase";

const summary = {
  path: "knowledge/fishing.md",
  title: "fishing",
  enabled: true,
  is_indexed: true,
} as KnowledgeDocumentSummary;

const savedDocument = { ...summary, content: "# 存檔內容" };

async function renderWithOpenDocument() {
  window.localStorage.setItem("kb-selected-file-path:fishing", summary.path);
  const view = renderHook(() => useKnowledgeBase());
  await waitFor(() => expect(view.result.current.openDocument?.path).toBe(summary.path));
  await waitFor(() => expect(view.result.current.editLoading).toBe(false));
  return view;
}

/** 讓語言更新卡在重抓文件那一步，測試才看得到中途的狀態。 */
async function startLanguageChangeUntilDocumentFetch(
  result: { current: ReturnType<typeof useKnowledgeBase> },
) {
  let resolveDocument: (value: unknown) => void = () => {};
  fetchKnowledgeDocumentMock.mockClear();
  fetchKnowledgeDocumentMock.mockReturnValue(new Promise((resolve) => { resolveDocument = resolve; }));

  let finished: Promise<void> = Promise.resolve();
  act(() => {
    finished = result.current.handleChangeLanguage(summary, "en");
  });
  await waitFor(() => expect(fetchKnowledgeDocumentMock).toHaveBeenCalledTimes(1));

  return {
    finish: () => act(async () => {
      resolveDocument({ ...savedDocument, language: "en", language_source: "manual" });
      await finished;
    }),
  };
}

describe("useKnowledgeBase language change", () => {
  beforeEach(() => {
    activeProjectId = "fishing";
    window.localStorage.clear();
    vi.clearAllMocks();
    fetchKnowledgeBaseDocumentsMock.mockResolvedValue({
      documents: [summary],
      directories: ["knowledge"],
    });
    fetchKnowledgeDocumentMock.mockResolvedValue({
      ...savedDocument,
      language: "zh",
      language_source: "auto",
    });
    updateKnowledgeDocumentMetaMock.mockResolvedValue({ status: "ok" });
  });

  it("keeps unsaved edits and refreshes the language of the open document", async () => {
    const { result } = await renderWithOpenDocument();
    act(() => result.current.updateEditContent("打到一半的內容"));
    fetchKnowledgeDocumentMock.mockResolvedValue({
      ...savedDocument,
      language: "en",
      language_source: "manual",
    });

    await act(async () => {
      await result.current.handleChangeLanguage(summary, "en");
    });

    expect(updateKnowledgeDocumentMetaMock).toHaveBeenCalledWith(summary.path, { language: "en" });
    expect(result.current.editContent).toBe("打到一半的內容");
    expect(result.current.editorDirty).toBe(true);
    expect(result.current.openDocument?.language).toBe("en");
  });

  it("does not flash the loading screen over the document", async () => {
    const { result } = await renderWithOpenDocument();
    const { finish } = await startLanguageChangeUntilDocumentFetch(result);

    expect(result.current.editLoading).toBe(false);

    await finish();
    expect(result.current.openDocument?.language).toBe("en");
  });

  it("does not bring the document back after switching to another project", async () => {
    const { result, rerender } = await renderWithOpenDocument();
    const { finish } = await startLanguageChangeUntilDocumentFetch(result);

    activeProjectId = "esg";
    rerender();
    await waitFor(() => expect(result.current.openDocument).toBeNull());

    await finish();
    expect(result.current.openDocument).toBeNull();
  });
});
