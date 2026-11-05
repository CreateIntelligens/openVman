import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { KnowledgeDocument } from "../api";
import { useKnowledgeBatchSelection } from "./useKnowledgeBatchSelection";

const openDocument = { path: "knowledge/a/guide.md", content: "server copy" } as KnowledgeDocument;

function renderSelection() {
  const options = {
    projectId: "p",
    documents: [],
    openDocument,
    loadDocuments: vi.fn(async () => undefined),
    closeFileView: vi.fn(),
    relocateOpenDocument: vi.fn(async () => undefined),
    // 舊版會用它重新讀檔；留著是為了確認不再呼叫。
    handleTreeSelect: vi.fn(),
    fetchQaTree: vi.fn(async () => undefined),
  };
  const { result } = renderHook(() => useKnowledgeBatchSelection(options));
  return { result, options };
}

// 審查重現：多選批次移動或改語言，會重新讀開著的文件，把沒存的修改蓋回伺服器版。
describe("useKnowledgeBatchSelection with the open document", () => {
  it("follows a batch move without reloading the document", async () => {
    const { result, options } = renderSelection();

    await act(async () => {
      await result.current.handleBatchFinished(
        "move",
        ["knowledge/a/guide.md"],
        (path) => path.replace("knowledge/a/", "knowledge/b/"),
      );
    });

    expect(options.relocateOpenDocument).toHaveBeenCalledWith("knowledge/b/guide.md");
    expect(options.handleTreeSelect).not.toHaveBeenCalled();
    expect(options.closeFileView).not.toHaveBeenCalled();
  });

  it("leaves the open document alone after a batch language change", async () => {
    const { result, options } = renderSelection();

    await act(async () => {
      await result.current.handleBatchFinished("language", ["knowledge/a/guide.md"], (path) => path);
    });

    expect(options.loadDocuments).toHaveBeenCalled();
    expect(options.relocateOpenDocument).not.toHaveBeenCalled();
    expect(options.handleTreeSelect).not.toHaveBeenCalled();
    expect(options.closeFileView).not.toHaveBeenCalled();
  });

  it("closes the document a batch delete removed", async () => {
    const { result, options } = renderSelection();

    await act(async () => {
      await result.current.handleBatchFinished("delete", ["knowledge/a/guide.md"], (path) => path);
    });

    expect(options.closeFileView).toHaveBeenCalled();
  });
});
