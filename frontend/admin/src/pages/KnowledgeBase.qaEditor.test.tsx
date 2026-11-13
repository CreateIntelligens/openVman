import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NavigationGuardProvider } from "../context/NavigationGuardContext";
import KnowledgeBase from "./KnowledgeBase";

// 這裡不 mock 任何 hook 或元件，只換掉網路：要鎖住的是「切換時未儲存的修改不會直接消失」，
// 這件事橫跨分類編輯器、頁面、導覽防呆三層，分開測看不出來有沒有接好。

vi.mock("../context/NavigationContext", () => ({
  useNavigation: () => ({ currentSubView: undefined, navigateTo: vi.fn() }),
}));

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "default" }),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: { id: "admin", username: "admin", role: "admin", disabled: false, created_at: "" } }),
}));

interface MergedRow {
  index: string;
  q: string;
  a: string;
  img: string;
  url: string;
  source_file: string;
  hidden: boolean;
}

interface ServerState {
  qaNodes: Array<Record<string, unknown>>;
  merged: Record<string, MergedRow[]>;
  documents: Array<Record<string, unknown>>;
  contents: Record<string, string>;
  mergedGets: string[];
  mergedPuts: Array<{ id: string; rows: MergedRow[] }>;
  nodeListGets: number;
}

let server: ServerState;

function ok(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
    headers: new Headers({ "content-type": "application/json" }),
  } as Response;
}

function route(url: string, init?: RequestInit): Response {
  const { pathname, searchParams } = new URL(url, "http://localhost");
  const method = init?.method ?? "GET";
  if (pathname.endsWith("/uploads/limits")) return ok({ document_max_upload_bytes: 1024 * 1024 });
  if (pathname.endsWith("/knowledge/base/documents")) {
    return ok({ documents: server.documents, document_count: server.documents.length, directories: [] });
  }
  if (pathname.endsWith("/knowledge/document")) {
    const path = searchParams.get("path") ?? "";
    const summary = server.documents.find((document) => document.path === path);
    return ok({ ...summary, content: server.contents[path] ?? "" });
  }
  if (pathname.endsWith("/knowledge/settings")) return ok({ language_routes: ["zh"] });
  if (pathname.endsWith("/knowledge/raw/pending")) return ok({ files: [] });
  if (pathname.endsWith("/knowledge/raw/commit/status")) {
    return ok({
      state: "idle",
      started_at: null,
      finished_at: null,
      files: {},
      committed: [],
      skipped: [],
      results: {},
      skip_reasons: {},
      error: null,
    });
  }
  const mergedMatch = pathname.match(/\/knowledge\/qa\/nodes\/([^/]+)\/merged$/);
  if (mergedMatch) {
    const id = decodeURIComponent(mergedMatch[1]);
    if (method === "PUT") {
      const rows = JSON.parse(init?.body as string) as MergedRow[];
      server.mergedPuts.push({ id, rows });
      server.merged[id] = rows;
      return ok({ status: "ok" });
    }
    server.mergedGets.push(id);
    return ok(server.merged[id] ?? []);
  }
  if (pathname.endsWith("/knowledge/qa/nodes")) {
    server.nodeListGets += 1;
    return ok(server.qaNodes);
  }
  throw new Error(`unexpected request: ${method} ${pathname}`);
}

function makeRows(labels: string[], sourceFile: string): MergedRow[] {
  return labels.map((label, position) => ({
    index: String(position + 1),
    q: label,
    a: `${label}的答案`,
    img: "",
    url: "",
    source_file: sourceFile,
    hidden: false,
  }));
}

function makeNode(id: string, label: string, questions: string[], sourceFile: string) {
  return {
    node_id: id,
    label,
    parent_ids: [],
    child_ids: [],
    order: 1,
    hidden: false,
    qa_entries: questions.map((question) => ({
      question,
      source_path: sourceFile,
      hidden: false,
      image_id: null,
    })),
    children: [],
  };
}

function makeDocument(path: string, overrides: Record<string, unknown> = {}) {
  return {
    path,
    title: path.split("/").pop(),
    category: "knowledge",
    extension: ".md",
    size: 10,
    updated_at: "2026-11-05T10:00:00",
    is_core: false,
    is_indexable: true,
    is_indexed: true,
    preview: "",
    source_type: "upload",
    source_url: null,
    enabled: true,
    created_at: "2026-11-05T10:00:00",
    language: "zh",
    ...overrides,
  };
}

const tree = () => screen.getByRole("tree", { name: "知識庫目錄" });
const inTree = (text: string) => within(tree()).getByText(text);
const articleOf = (question: string) =>
  screen.getByDisplayValue(question).closest("article") as HTMLElement;

function expandInTree(label: string) {
  const row = inTree(label).closest('[role="treeitem"]') as HTMLElement;
  fireEvent.click(within(row).getByText("chevron_right"));
}

async function openPage() {
  render(
    <NavigationGuardProvider>
      <KnowledgeBase />
    </NavigationGuardProvider>,
  );
  await within(await screen.findByRole("tree", { name: "知識庫目錄" })).findByText("分類甲");
}

async function openCategoryA() {
  await openPage();
  fireEvent.click(inTree("分類甲"));
  return screen.findByDisplayValue("甲一");
}

async function chooseInDialog(button: string) {
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: button }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
}

const originalScrollIntoView = Element.prototype.scrollIntoView;
let scrolledTo: Element[] = [];

beforeEach(() => {
  window.localStorage.clear();
  sessionStorage.clear();
  scrolledTo = [];
  // 頁首分頁也會捲動，這裡只看問答列。
  Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
    if (this.tagName === "ARTICLE") scrolledTo.push(this);
  };
  server = {
    qaNodes: [
      makeNode("a", "分類甲", ["甲一", "甲二", "甲三"], "knowledge/qa/a.csv"),
      makeNode("b", "分類乙", ["乙一", "乙二"], "knowledge/qa/b.csv"),
    ],
    merged: {
      a: makeRows(["甲一", "甲二", "甲三"], "knowledge/qa/a.csv"),
      b: makeRows(["乙一", "乙二"], "knowledge/qa/b.csv"),
    },
    documents: [makeDocument("knowledge/guide.md"), makeDocument("knowledge/other.md")],
    contents: {
      "knowledge/guide.md": "# 指南內容",
      "knowledge/other.md": "# 其他內容",
    },
    mergedGets: [],
    mergedPuts: [],
    nodeListGets: 0,
  };
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => route(String(input), init));
});

afterEach(() => {
  Element.prototype.scrollIntoView = originalScrollIntoView;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("unsaved quick QA edits", () => {
  // 實測：切換分類時，未儲存的修改會直接消失。
  it("asks before switching category, keeps the edit when told to stay, and drops it when told to leave", async () => {
    fireEvent.change(await openCategoryA(), { target: { value: "改過的甲一" } });

    fireEvent.click(inTree("分類乙"));

    expect(within(await screen.findByRole("dialog")).getByText("尚有未儲存的變更")).toBeTruthy();
    expect(server.mergedGets).not.toContain("b");

    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
    expect(screen.getByText("有未儲存的變更")).toBeTruthy();
    expect(server.mergedGets).not.toContain("b");

    fireEvent.click(inTree("分類乙"));
    await chooseInDialog("捨棄並離開");

    expect(await screen.findByDisplayValue("乙一")).toBeTruthy();
    expect(screen.queryByDisplayValue("改過的甲一")).toBeNull();

    // 捨棄之後就乾淨了，不能每次切換都再問一次。
    fireEvent.click(inTree("分類甲"));
    expect(await screen.findByDisplayValue("甲一")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks before opening a document from the tree", async () => {
    fireEvent.change(await openCategoryA(), { target: { value: "改過的甲一" } });

    fireEvent.click(inTree("guide.md"));
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();

    fireEvent.click(inTree("guide.md"));
    await chooseInDialog("捨棄並離開");

    expect(await screen.findByDisplayValue("# 指南內容")).toBeTruthy();
    expect(screen.queryByText("有未儲存的變更")).toBeNull();
  });

  it("asks before going back to the add-data screen", async () => {
    fireEvent.change(await openCategoryA(), { target: { value: "改過的甲一" } });

    fireEvent.click(screen.getByRole("button", { name: "新增資料" }));
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
  });

  it("does not ask when the category on screen is clicked again, and keeps the edit", async () => {
    fireEvent.change(await openCategoryA(), { target: { value: "改過的甲一" } });

    fireEvent.click(inTree("分類甲"));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
  });

  it("does not ask once the edit was saved, and tells the page's shared message", async () => {
    fireEvent.change(await openCategoryA(), { target: { value: "改過的甲一" } });
    const nodeListsBeforeSave = server.nodeListGets;

    fireEvent.click(screen.getByRole("button", { name: "儲存變更" }));

    expect(await screen.findByText("已儲存，AI 和選單都會用新內容")).toBeTruthy();
    expect(server.mergedPuts).toHaveLength(1);
    expect(server.mergedPuts[0].id).toBe("a");
    expect(server.mergedPuts[0].rows.map((row) => [row.index, row.q])).toEqual([
      ["1", "改過的甲一"],
      ["2", "甲二"],
      ["3", "甲三"],
    ]);
    await waitFor(() => expect(screen.queryByText("有未儲存的變更")).toBeNull());
    // 樹上的題目也要跟著更新，不必重新整理頁面。
    await waitFor(() => expect(server.nodeListGets).toBeGreaterThan(nodeListsBeforeSave));

    fireEvent.click(inTree("分類乙"));
    expect(await screen.findByDisplayValue("乙一")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("messages from the category editor", () => {
  it("keeps an error on screen until it is dealt with, and clears it on leaving the category", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.change(await openCategoryA(), { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: "儲存變更" }));

    const message = "第 1 題：問題和答案都要填，填好再儲存。";
    expect(await screen.findByText(message)).toBeTruthy();
    expect(server.mergedPuts).toHaveLength(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(screen.getByText(message)).toBeTruthy();

    fireEvent.click(inTree("分類乙"));
    await chooseInDialog("捨棄並離開");

    expect(await screen.findByDisplayValue("乙一")).toBeTruthy();
    expect(screen.queryByText(message)).toBeNull();
  });
});

describe("jumping to a question from the tree", () => {
  it("opens the other category, then scrolls to the question and marks it", async () => {
    await openPage();
    expandInTree("分類乙");

    fireEvent.click(inTree("乙二"));

    const question = await screen.findByDisplayValue("乙二");
    await waitFor(() => expect(scrolledTo).toEqual([question.closest("article")]));
    expect(articleOf("乙二").getAttribute("data-highlighted")).toBe("true");
    expect(articleOf("乙一").getAttribute("data-highlighted")).toBeNull();
  });

  it("scrolls inside the open category without asking, keeping the unsaved edit, and again on a second click", async () => {
    const first = await openCategoryA();
    fireEvent.change(first, { target: { value: "改過的甲一" } });
    // 點分類名稱就已經展開，題目直接在樹上。

    fireEvent.click(inTree("甲三"));

    await waitFor(() => expect(scrolledTo).toEqual([articleOf("甲三")]));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();

    fireEvent.click(inTree("甲三"));
    await waitFor(() => expect(scrolledTo).toHaveLength(2));
  });

  it("asks first when the question is in another category and something is unsaved", async () => {
    fireEvent.change(await openCategoryA(), { target: { value: "改過的甲一" } });
    expandInTree("分類乙");

    fireEvent.click(inTree("乙二"));
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
    expect(scrolledTo).toHaveLength(0);

    fireEvent.click(inTree("乙二"));
    await chooseInDialog("捨棄並離開");

    const question = await screen.findByDisplayValue("乙二");
    await waitFor(() => expect(scrolledTo).toEqual([question.closest("article")]));
  });
});

describe("unsaved document edits", () => {
  // 實測：切換文件時，未儲存的修改一樣會直接消失。
  it("asks before switching document, and keeps the text when told to stay", async () => {
    await openPage();
    fireEvent.click(inTree("guide.md"));
    fireEvent.change(await screen.findByDisplayValue("# 指南內容"), { target: { value: "# 改過的指南" } });

    fireEvent.click(inTree("other.md"));
    expect(within(await screen.findByRole("dialog")).getByText("尚有未儲存的變更")).toBeTruthy();
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("# 改過的指南")).toBeTruthy();

    fireEvent.click(inTree("other.md"));
    await chooseInDialog("捨棄並離開");

    expect(await screen.findByDisplayValue("# 其他內容")).toBeTruthy();
  });

  it("asks before leaving a document for a category", async () => {
    await openPage();
    fireEvent.click(inTree("guide.md"));
    fireEvent.change(await screen.findByDisplayValue("# 指南內容"), { target: { value: "# 改過的指南" } });

    fireEvent.click(inTree("分類甲"));
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("# 改過的指南")).toBeTruthy();
    expect(server.mergedGets).toHaveLength(0);
  });

  it("asks only once when leaving a QA document through its go-to-category button", async () => {
    server.documents = [
      makeDocument("knowledge/faq.md", { source_type: "qa", qa_attached: true }),
    ];
    server.contents = { "knowledge/faq.md": "## 甲一\n\n甲一的答案\n" };
    server.qaNodes = [makeNode("a", "分類甲", ["甲一"], "knowledge/faq.md")];
    server.merged = { a: makeRows(["甲一"], "knowledge/faq.md") };
    await openPage();
    fireEvent.click(inTree("faq.md"));
    fireEvent.change(await screen.findByDisplayValue("甲一"), { target: { value: "改過的甲一" } });

    fireEvent.click(screen.getByRole("button", { name: "前往快速問答" }));
    await chooseInDialog("不儲存，離開");

    expect((await screen.findByRole("heading", { name: "分類甲" }))).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
