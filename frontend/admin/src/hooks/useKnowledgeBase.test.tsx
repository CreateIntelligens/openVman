import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchKnowledgeBaseDocumentsMock = vi.fn();
const fetchKnowledgeDocumentMock = vi.fn();
let activeProjectId = "fishing";

vi.mock("../api", () => ({
  fetchKnowledgeBaseDocuments: () => fetchKnowledgeBaseDocumentsMock(),
  fetchKnowledgeDocument: (path: string) => fetchKnowledgeDocumentMock(path),
}));

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: activeProjectId }),
}));

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
});
