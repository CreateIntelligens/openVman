import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Workspace from "./Workspace";
import { NavigationGuardProvider } from "../context/NavigationGuardContext";
import { fetchKnowledgeDocument } from "../api";

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "proj-test" }),
}));

function summary(path: string, title: string) {
  return {
    path,
    title,
    category: "",
    extension: ".md",
    size: 10,
    updated_at: "2026-10-22T00:00:00Z",
    is_core: false,
    is_indexable: true,
    is_indexed: true,
    preview: "",
    source_type: "manual" as const,
    source_url: null,
    enabled: true,
    created_at: "2026-10-22T00:00:00Z",
  };
}

vi.mock("../api", () => ({
  deleteKnowledgeDocument: vi.fn(),
  fetchKnowledgeDocument: vi.fn(async (path: string) => ({ path, content: `內容：${path}` })),
  fetchKnowledgeDocuments: vi.fn(async () => ({
    documents: [summary("a.md", "文件甲"), summary("b.md", "文件乙")],
  })),
  moveKnowledgeDocument: vi.fn(),
  reindexKnowledge: vi.fn(),
  saveKnowledgeDocument: vi.fn(),
  uploadKnowledgeDocuments: vi.fn(),
}));

const opened = () => vi.mocked(fetchKnowledgeDocument).mock.calls.map(([path]) => path);

async function editorWithDraft() {
  const textarea = (await waitFor(() => {
    const element = document.getElementById("knowledge-content");
    if (!element) throw new Error("編輯區還沒出現");
    return element;
  })) as HTMLTextAreaElement;
  await waitFor(() => expect(textarea.value).toBe("內容：a.md"));
  fireEvent.change(textarea, { target: { value: "還沒存的修改" } });
  return textarea;
}

describe("Workspace unsaved changes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("asks before opening another document and keeps the draft when the user stays", async () => {
    render(
      <NavigationGuardProvider>
        <Workspace />
      </NavigationGuardProvider>,
    );
    const textarea = await editorWithDraft();

    fireEvent.click(screen.getByRole("button", { name: /文件乙/ }));
    expect(await screen.findByText("尚有未儲存的變更")).toBeTruthy();
    expect(opened()).not.toContain("b.md");

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(textarea.value).toBe("還沒存的修改");

    fireEvent.click(screen.getByRole("button", { name: /文件乙/ }));
    fireEvent.click(await screen.findByRole("button", { name: "捨棄並離開" }));
    await waitFor(() => expect(opened()).toContain("b.md"));
  });

  it("asks before starting a new document or reloading the list over unsaved edits", async () => {
    render(
      <NavigationGuardProvider>
        <Workspace />
      </NavigationGuardProvider>,
    );
    const textarea = await editorWithDraft();

    fireEvent.click(screen.getByRole("button", { name: "新文件" }));
    expect(await screen.findByText("尚有未儲存的變更")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(textarea.value).toBe("還沒存的修改");

    fireEvent.click(screen.getByRole("button", { name: "重新整理文件清單" }));
    expect(await screen.findByText("尚有未儲存的變更")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(textarea.value).toBe("還沒存的修改");
  });
});
