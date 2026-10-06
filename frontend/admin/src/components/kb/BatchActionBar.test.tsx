import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeDocumentSummary } from "../../api";
import BatchActionBar from "./BatchActionBar";

const api = vi.hoisted(() => ({
  deleteKnowledgeDocument: vi.fn(),
  moveKnowledgeDocument: vi.fn(),
  updateKnowledgeDocumentMeta: vi.fn(),
}));

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, ...api };
});

function makeDoc(path: string, overrides: Partial<KnowledgeDocumentSummary> = {}): KnowledgeDocumentSummary {
  return {
    path,
    title: path.split("/").pop() ?? path,
    category: "knowledge",
    extension: ".md",
    size: 10,
    updated_at: "2026-10-01T00:00:00Z",
    is_core: false,
    is_indexable: true,
    is_indexed: true,
    preview: "",
    source_type: "manual",
    source_url: null,
    enabled: true,
    created_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

const documents = [
  makeDoc("knowledge/a.md"),
  makeDoc("knowledge/b.md"),
  makeDoc("knowledge/archive/old.md"),
];

function renderBar(selectedPaths = ["knowledge/a.md", "knowledge/b.md"]) {
  const props = {
    selectedPaths,
    documents,
    serverDirs: ["knowledge/archive"],
    onClearSelection: vi.fn(),
    onSelectionChange: vi.fn(),
    onFinished: vi.fn<ComponentProps<typeof BatchActionBar>["onFinished"]>(async () => undefined),
    onStatus: vi.fn(),
    onRunningChange: vi.fn(),
  };
  const view = render(<BatchActionBar {...props} />);
  return { ...view, props };
}

describe("BatchActionBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.deleteKnowledgeDocument.mockResolvedValue({ status: "ok" });
    api.moveKnowledgeDocument.mockResolvedValue({ status: "ok" });
    api.updateKnowledgeDocumentMeta.mockResolvedValue({ status: "ok" });
  });

  it("shows the selection count and clears it", () => {
    const { props } = renderBar();

    expect(screen.getByText("已選 2 個檔案")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "全部取消" }));
    expect(props.onClearSelection).toHaveBeenCalled();
  });

  it("disables the actions when nothing is selected", () => {
    renderBar([]);

    expect((screen.getByRole("button", { name: /移動到/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "刪除" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("deletes only after confirming, listing the count and names", async () => {
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "刪除" }));

    expect(screen.getByText(/確定要刪除 2 個檔案嗎？/).textContent).toContain("• a.md\n• b.md");
    expect(api.deleteKnowledgeDocument).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "刪除 2 個" }));

    await waitFor(() =>
      expect(props.onStatus).toHaveBeenLastCalledWith({ type: "success", message: "刪除完成 2 個" }),
    );
    expect(api.deleteKnowledgeDocument.mock.calls).toEqual([["knowledge/a.md"], ["knowledge/b.md"]]);
    expect(props.onFinished).toHaveBeenCalledTimes(1);
    expect(props.onFinished.mock.calls[0]).toEqual(
      expect.arrayContaining(["delete", ["knowledge/a.md", "knowledge/b.md"]]),
    );
    expect(props.onSelectionChange).toHaveBeenCalledWith([]);
  });

  it("does not delete when the confirmation is cancelled", () => {
    renderBar();

    fireEvent.click(screen.getByRole("button", { name: "刪除" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(api.deleteKnowledgeDocument).not.toHaveBeenCalled();
  });

  it("moves each file into the chosen directory keeping its filename", async () => {
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: /移動到/ }));
    expect(screen.getByText("移動 2 個文件")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /archive/ }));
    fireEvent.click(screen.getByRole("button", { name: "移動" }));

    await waitFor(() => expect(props.onFinished).toHaveBeenCalledTimes(1));
    expect(api.moveKnowledgeDocument.mock.calls).toEqual([
      ["knowledge/a.md", "knowledge/archive/a.md"],
      ["knowledge/b.md", "knowledge/archive/b.md"],
    ]);
    const targetPathOf = props.onFinished.mock.calls[0][2];
    expect(targetPathOf("knowledge/a.md")).toBe("knowledge/archive/a.md");
  });

  it("keeps going after a failure, summarises it and keeps the failed file selected", async () => {
    api.moveKnowledgeDocument.mockImplementation(async (source: string) => {
      if (source === "knowledge/a.md") throw new Error("目標路徑已存在");
      return { status: "ok" };
    });
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: /移動到/ }));
    fireEvent.click(screen.getByRole("button", { name: /archive/ }));
    fireEvent.click(screen.getByRole("button", { name: "移動" }));

    await waitFor(() =>
      expect(props.onStatus).toHaveBeenLastCalledWith({
        type: "error",
        message: "移動完成 1 個，1 個失敗：a.md（目標路徑已存在）",
      }),
    );
    expect(api.moveKnowledgeDocument).toHaveBeenCalledTimes(2);
    expect(props.onSelectionChange).toHaveBeenCalledWith(["knowledge/a.md"]);
    expect(props.onFinished).toHaveBeenCalledTimes(1);
    expect(props.onFinished.mock.calls[0][1]).toEqual(["knowledge/b.md"]);
  });

  it("refuses to move files attached to the quick-QA tree without calling the API", async () => {
    const attached = makeDoc("knowledge/qa.md", { source_type: "qa", qa_attached: true });
    const props = {
      selectedPaths: ["knowledge/qa.md"],
      documents: [...documents, attached],
      serverDirs: ["knowledge/archive"],
      onClearSelection: vi.fn(),
      onSelectionChange: vi.fn(),
      onFinished: vi.fn(),
      onStatus: vi.fn(),
    };
    render(<BatchActionBar {...props} />);

    fireEvent.click(screen.getByRole("button", { name: /移動到/ }));
    fireEvent.click(screen.getByRole("button", { name: /archive/ }));
    fireEvent.click(screen.getByRole("button", { name: "移動" }));

    await waitFor(() => expect(props.onStatus).toHaveBeenCalledTimes(2));
    expect(api.moveKnowledgeDocument).not.toHaveBeenCalled();
    expect(props.onSelectionChange).toHaveBeenCalledWith(["knowledge/qa.md"]);
  });

  it("applies the same language to every selected file", async () => {
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: /設定語言/ }));
    fireEvent.click(screen.getByRole("radio", { name: /English/ }));
    fireEvent.click(screen.getByRole("button", { name: "套用" }));

    await waitFor(() =>
      expect(props.onStatus).toHaveBeenLastCalledWith({ type: "success", message: "語言設定完成 2 個" }),
    );
    expect(api.updateKnowledgeDocumentMeta.mock.calls).toEqual([
      ["knowledge/a.md", { language: "en" }],
      ["knowledge/b.md", { language: "en" }],
    ]);
  });

  it("hides the actions and shows progress while a batch is running", async () => {
    let release: () => void = () => undefined;
    api.deleteKnowledgeDocument.mockImplementationOnce(
      () => new Promise((resolve) => { release = () => resolve({ status: "ok" }); }),
    );
    const { props } = renderBar();

    fireEvent.click(screen.getByRole("button", { name: "刪除" }));
    fireEvent.click(screen.getByRole("button", { name: "刪除 2 個" }));

    expect(await screen.findByText(/刪除中 0\/2/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /移動到/ })).toBeNull();
    expect((screen.getByRole("button", { name: "全部取消" }) as HTMLButtonElement).disabled).toBe(true);
    expect(props.onRunningChange).toHaveBeenCalledWith(true);

    release();

    await waitFor(() => expect(props.onRunningChange).toHaveBeenLastCalledWith(false));
    expect(screen.getByRole("button", { name: /移動到/ })).toBeTruthy();
  });
});
