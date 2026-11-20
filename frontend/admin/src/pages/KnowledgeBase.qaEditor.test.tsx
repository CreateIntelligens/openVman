import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AccountProfile } from "../api/auth";
import type { QaAllQuestions, QaCategorySummary } from "../api/knowledge";
import { NavigationGuardProvider } from "../context/NavigationGuardContext";
import { writeScoped } from "../utils/scopedStorage";
import type { MergedQaItem, QaNode } from "../hooks/useQaNodes";
import KnowledgeBase from "./KnowledgeBase";

// 題庫與文件使用真正的頁面、編輯器、API client 和導覽防呆。
const mocks = vi.hoisted(() => ({ navigateTo: vi.fn(), openChatTest: vi.fn(), vendor: false }));

vi.mock("../context/NavigationContext", async () => {
  const { useNavigationGuard } = await import("../context/NavigationGuardContext");
  return {
    useNavigation: () => {
      const { requestNavigation } = useNavigationGuard();
      return {
        currentSubView: undefined,
        navigateTo: mocks.navigateTo,
        openChatTest: (options: unknown) => requestNavigation(() => mocks.openChatTest(options)),
      };
    },
  };
});

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "default" }),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    account: {
      id: "test", username: "test", role: mocks.vendor ? "user" : "admin", disabled: false, created_at: "",
      ...(mocks.vendor ? { vendor_name: "測試廠商" } : {}),
    } satisfies AccountProfile,
  }),
}));

interface ServerState {
  qaNodes: QaNode[];
  merged: Record<string, MergedQaItem[]>;
  uncategorized: MergedQaItem[];
  documents: Array<Record<string, unknown>>;
  contents: Record<string, string>;
  mergedGets: string[];
  mergedPuts: Array<{ id: string; rows: MergedQaItem[]; baseVersion: string | null }>;
  questionPuts: Array<Record<string, unknown>>;
  questionMoves: Array<{
    to_node_id: string;
    items: Array<{ question: string; source_path: string; from_node_ids: string[] }>;
  }>;
  entryWrites: Array<{ id: string; method: string; question: string; sourcePath: string }>;
  categoryWrites: Array<{ id: string; hidden: boolean }>;
  imageUploads: File[];
  nodeListGets: number;
  questionListGets: number;
  failSave: boolean;
  saveRejection?: { status: number; detail: string };
  failMove?: { status: number; detail: string };
  failTreeRefresh?: boolean;
  refuseDetach?: string;
}

let server: ServerState;

function ok(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => structuredClone(payload),
    headers: new Headers({ "content-type": "application/json" }),
  } as Response;
}

function reject(status: number, detail: string) {
  return new Response(JSON.stringify({ detail }), {
    status, headers: { "content-type": "application/json" },
  });
}

function allQuestions(): QaAllQuestions {
  const categories: QaCategorySummary[] = [];
  const questions: QaAllQuestions["questions"] = [];
  const visit = (nodes: QaNode[], parent?: QaCategorySummary) => {
    for (const node of nodes) {
      const category = {
        node_id: node.node_id,
        label: node.label,
        path: [...(parent?.path ?? []), node.label],
        parent_id: parent?.node_id ?? null,
        hidden: Boolean(parent?.hidden || node.hidden),
      };
      categories.push(category);
      for (const item of server.merged[node.node_id] ?? []) {
        const existing = questions.find((row) => row.question === item.q && row.source.path === item.source_file);
        if (existing) {
          existing.category_ids.push(node.node_id);
          existing.category_hidden &&= category.hidden;
          continue;
        }
        questions.push({
          id: `${item.source_file}:${item.q}`,
          question: item.q,
          answer: item.a,
          image: item.img ?? "",
          image_kind: item.image_kind,
          url: item.url ?? "",
          language: item.source_file.endsWith("/b.csv") ? "en" : "zh",
          source: { kind: "file", path: item.source_file, label: item.source_file.split("/").pop()! },
          content_hash: "hash-1",
          category_ids: [node.node_id],
          category_hidden: category.hidden,
          hidden_in_file: Boolean(item.hidden),
          document_enabled: true,
          no_answer: !item.a,
          off_menu: null,
        });
      }
      visit(node.children ?? [], category);
    }
  };
  visit(server.qaNodes);
  for (const item of server.uncategorized) {
    questions.push({
      id: `${item.source_file}:${item.q}`,
      question: item.q,
      answer: item.a,
      image: item.img ?? "",
      image_kind: item.image_kind,
      url: item.url ?? "",
      language: "zh",
      source: { kind: "file", path: item.source_file, label: item.source_file.split("/").pop()! },
      content_hash: item.base_version ?? "hash-off",
      category_ids: [],
      category_hidden: false,
      hidden_in_file: Boolean(item.hidden),
      document_enabled: true,
      no_answer: !item.a,
      off_menu: "never",
    });
  }
  return { categories, questions };
}

function route(url: string, init?: RequestInit): Response {
  const { pathname, searchParams } = new URL(url, "http://localhost");
  const method = init?.method ?? "GET";
  if (pathname.endsWith("/uploads/limits")) return ok({ document_max_upload_bytes: 1024 * 1024 });
  if (pathname.endsWith("/knowledge/base/documents")) {
    return ok({ documents: server.documents, document_count: server.documents.length, directories: [] });
  }
  if (/\/knowledge\/(?:base\/)?document$/.test(pathname)) {
    const path = searchParams.get("path") ?? "";
    const summary = server.documents.find((document) => document.path === path);
    return ok({ ...summary, content: server.contents[path] ?? "" });
  }
  if (pathname.endsWith("/knowledge/qa/questions") && method === "PUT") {
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    server.questionPuts.push(body);
    if (server.saveRejection) return reject(server.saveRejection.status, server.saveRejection.detail);
    if (server.failSave) {
      return reject(409, "這份文件在你編輯時被改過了，請重新載入後再存檔");
    }
    if (!String(body.a ?? "").trim()) return reject(400, "答案不可空白，未做任何變更");
    const target = server.uncategorized.find(
      (item) => item.q === body.original_q && item.source_file === body.source_path,
    ) ?? Object.values(server.merged).flat().find(
      (item) => item.q === body.original_q && item.source_file === body.source_path,
    );
    if (!target) return reject(404, "這份文件裡沒有這個題目");
    target.q = String(body.q ?? "");
    target.original_q = target.q;
    target.a = String(body.a ?? "");
    target.img = String(body.img ?? "");
    target.url = String(body.url ?? "");
    target.hidden = Boolean(body.hidden);
    target.base_version = "hash-2";
    return ok({
      question: {
        q: target.q,
        a: target.a,
        img: target.img,
        url: target.url,
        hidden: target.hidden,
      },
      content_hash: "hash-2",
    });
  }
  if (pathname.endsWith("/knowledge/qa/questions/move") && method === "POST") {
    const body = JSON.parse(init?.body as string) as {
      to_node_id: string;
      items: Array<{ question: string; source_path: string; from_node_ids: string[] }>;
    };
    server.questionMoves.push({ to_node_id: body.to_node_id, items: body.items });
    if (server.failMove) return reject(server.failMove.status, server.failMove.detail);
    if (server.refuseDetach) return reject(503, "暫時無法取下題目");
    for (const item of body.items) {
      const copied = Object.values(server.merged).flat().find(
        (row) => row.q === item.question && row.source_file === item.source_path,
      ) ?? server.uncategorized.find(
        (row) => row.q === item.question && row.source_file === item.source_path,
      );
      if (!copied) return reject(404, `「${item.question}」不在原本的分類裡，請重新整理`);
      const existing = (server.merged[body.to_node_id] ?? []).find((row) => row.q === item.question);
      if (existing && existing.source_file !== item.source_path) {
        return reject(400, `「${item.question}」在目標分類已經有相同的題目`);
      }
      for (const fid of item.from_node_ids) {
        if (fid === body.to_node_id) continue;
        server.merged[fid] = (server.merged[fid] ?? []).filter(
          (row) => row.q !== item.question || row.source_file !== item.source_path,
        );
      }
      if (!item.from_node_ids.length) {
        server.uncategorized = server.uncategorized.filter(
          (row) => row.q !== item.question || row.source_file !== item.source_path,
        );
      }
      if (!existing) {
        server.merged[body.to_node_id] = [...(server.merged[body.to_node_id] ?? []), { ...copied }];
      }
    }
    return ok({ to: { node_id: body.to_node_id }, from: [] });
  }
  if (pathname.endsWith("/knowledge/qa/questions")) {
    server.questionListGets += 1;
    return ok(allQuestions());
  }
  if (pathname.endsWith("/knowledge/qa/images") && method === "POST") {
    server.imageUploads.push((init?.body as FormData).get("file") as File);
    return ok({ image_id: "new-image.png", image_kind: "qr" });
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
      const rows = JSON.parse(init?.body as string) as MergedQaItem[];
      server.mergedPuts.push({ id, rows, baseVersion: searchParams.get("base_version") });
      if (server.saveRejection) return reject(server.saveRejection.status, server.saveRejection.detail);
      if (server.failSave) {
        return new Response(JSON.stringify({ detail: "hidden-file.csv changed" }), { status: 409 });
      }
      for (const row of rows) {
        if (!row.source_file || !row.original_q || row.original_q === row.q) continue;
        for (const [otherId, otherRows] of Object.entries(server.merged)) {
          if (otherId === id) continue;
          server.merged[otherId] = otherRows.map((item) =>
            item.source_file === row.source_file && item.q === row.original_q
              ? { ...item, q: row.q, original_q: row.q }
              : item,
          );
        }
      }
      server.merged[id] = rows.map((row) => ({ ...row, original_q: row.q }));
      return ok({ status: "ok" });
    }
    server.mergedGets.push(id);
    return ok(server.merged[id] ?? []);
  }
  const entryMatch = pathname.match(/\/knowledge\/qa\/nodes\/([^/]+)\/entries$/);
  if (entryMatch) {
    const id = decodeURIComponent(entryMatch[1]);
    const body = method === "POST" ? JSON.parse(init?.body as string) : Object.fromEntries(searchParams);
    const entry = { id, method, question: body.question, sourcePath: body.source_path };
    server.entryWrites.push(entry);
    if (method === "DELETE" && server.refuseDetach === id) return reject(503, "暫時無法取下題目");
    if (method === "POST") {
      const copied = Object.values(server.merged).flat().find(
        (row) => row.q === entry.question && row.source_file === entry.sourcePath,
      );
      if (!copied) throw new Error("missing source row");
      server.merged[id] = [...server.merged[id], copied];
    } else {
      server.merged[id] = server.merged[id].filter(
        (row) => row.q !== entry.question || row.source_file !== entry.sourcePath,
      );
    }
    return ok({ status: "ok" });
  }
  const nodeMatch = pathname.match(/\/knowledge\/qa\/nodes\/([^/]+)$/);
  if (nodeMatch && method === "PATCH") {
    const id = decodeURIComponent(nodeMatch[1]);
    const updates = JSON.parse(init?.body as string);
    const node = server.qaNodes.find((item) => item.node_id === id);
    if (!node) throw new Error("missing node");
    node.hidden = updates.hidden;
    server.categoryWrites.push({ id, hidden: node.hidden });
    return ok(node);
  }
  if (pathname.endsWith("/knowledge/qa/nodes")) {
    server.nodeListGets += 1;
    if (server.failTreeRefresh) return reject(503, "讀不到分類樹");
    return ok(server.qaNodes);
  }
  throw new Error(`unexpected request: ${method} ${pathname}`);
}

function makeRows(labels: string[], sourceFile: string): MergedQaItem[] {
  return labels.map((label, position) => ({
    index: String(position + 1),
    q: label,
    a: `${label}的答案`,
    img: "",
    url: "",
    source_file: sourceFile,
    hidden: false,
    original_q: label,
    base_version: "base-1",
  }));
}

function makeNode(id: string, label: string, questions: string[], sourceFile: string): QaNode {
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

const sidebar = () => screen.getByRole("tree", { name: "知識庫目錄" });
const inTree = (text: string) => within(sidebar()).getByText(text);
const table = () => screen.getByRole("table", { name: "題庫表格" });
const rowButton = (question: string) => within(table()).getByRole("button", { name: question });
const editor = () => screen.getByRole("complementary", { name: "編輯題目" });

async function openPage() {
  render(
    <NavigationGuardProvider>
      <KnowledgeBase />
    </NavigationGuardProvider>,
  );
  await screen.findByRole("table", { name: "題庫表格" });
}

async function editQuestion(question: string) {
  fireEvent.click(rowButton(question));
  const input = await screen.findByDisplayValue(question);
  await waitFor(() => expect(input.matches(":disabled")).toBe(false));
  return input;
}

async function openQuestionA() {
  await openPage();
  return editQuestion("甲一");
}

async function chooseInDialog(button: string) {
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: button }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
}

function searchFor(term: string) {
  fireEvent.change(screen.getByRole("searchbox", { name: "搜尋問題或答案" }), { target: { value: term } });
  return within(screen.getByRole("list", { name: "題目搜尋結果" }));
}

const originalScrollIntoView = Element.prototype.scrollIntoView;
const scrolledTo: Element[] = [];

beforeEach(() => {
  mocks.vendor = false;
  mocks.navigateTo.mockClear();
  mocks.openChatTest.mockClear();
  window.localStorage.clear();
  sessionStorage.clear();
  scrolledTo.length = 0;
  Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
    if (this.textContent?.trim() === "編輯題目") scrolledTo.push(this);
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
    uncategorized: [],
    documents: [makeDocument("knowledge/guide.md"), makeDocument("knowledge/other.md")],
    contents: {
      "knowledge/guide.md": "# 指南內容",
      "knowledge/other.md": "# 其他內容",
    },
    mergedGets: [],
    mergedPuts: [],
    questionPuts: [],
    questionMoves: [],
    entryWrites: [],
    categoryWrites: [],
    imageUploads: [],
    nodeListGets: 0,
    questionListGets: 0,
    failSave: false,
  };
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => route(String(input), init));
});

afterEach(() => {
  Element.prototype.scrollIntoView = originalScrollIntoView;
  vi.restoreAllMocks();
});

describe("題目編輯與未儲存的變更", () => {
  it("切換分類前詢問，取消保留草稿，捨棄後切換且不影響下一次操作", async () => {
    await openPage();
    fireEvent.click(inTree("分類甲"));
    fireEvent.change(await editQuestion("甲一"), { target: { value: "改過的甲一" } });

    fireEvent.click(inTree("分類乙"));
    expect(within(await screen.findByRole("dialog")).getByText("尚有未儲存的變更")).toBeTruthy();
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
    expect(server.mergedGets).not.toContain("b");

    fireEvent.click(inTree("分類乙"));
    await chooseInDialog("捨棄並離開");
    await screen.findByRole("heading", { name: "分類乙" });

    await editQuestion("乙一");
    expect(screen.queryByDisplayValue("改過的甲一")).toBeNull();

    fireEvent.click(inTree("分類甲"));
    await editQuestion("甲一");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("開啟文件前詢問，捨棄後才顯示文件", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "改過的甲一" } });

    fireEvent.click(inTree("guide.md"));
    await chooseInDialog("取消");
    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();

    fireEvent.click(inTree("guide.md"));
    await chooseInDialog("捨棄並離開");
    expect(await screen.findByDisplayValue("# 指南內容")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "編輯題目" })).toBeNull();
  });

  it("按上傳前詢問使用者是否要捨棄草稿", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "改過的甲一" } });

    fireEvent.click(screen.getByRole("button", { name: "上傳" }));
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
  });

  it("再次點選編輯中的題目時保留草稿且不詢問", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "改過的甲一" } });

    fireEvent.click(rowButton("甲一"));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
  });

  it("再次點選目前分類時保留面板中的草稿且不詢問", async () => {
    await openPage();
    fireEvent.click(inTree("分類甲"));
    fireEvent.change(await editQuestion("甲一"), { target: { value: "改過的甲一" } });

    fireEvent.click(inTree("分類甲"));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
  });

  it("儲存送出版本與原問題，更新題庫且再次切換不詢問", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "改過的甲一" } });
    const nodeListsBeforeSave = server.nodeListGets;

    fireEvent.click(within(editor()).getByRole("button", { name: "儲存" }));

    expect(await screen.findByText("已儲存題目。")).toBeTruthy();
    expect(server.mergedPuts).toHaveLength(1);
    expect(server.mergedPuts[0]).toMatchObject({ id: "a", baseVersion: "base-1" });
    expect(server.mergedPuts[0].rows.map((row) => [row.index, row.q, row.original_q])).toEqual([
      ["1", "改過的甲一", "甲一"],
      ["2", "甲二", "甲二"],
      ["3", "甲三", "甲三"],
    ]);
    expect(rowButton("改過的甲一")).toBeTruthy();
    expect(server.nodeListGets).toBeGreaterThan(nodeListsBeforeSave);

    await editQuestion("乙一");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("儲存衝突顯示可操作的訊息並保留草稿，關閉時仍詢問", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "改過的甲一" } });
    server.failSave = true;
    fireEvent.click(within(editor()).getByRole("button", { name: "儲存" }));

    const alert = await within(editor()).findByRole("alert");
    expect(alert.textContent).toContain("有人同時修改了題目，請重新整理後再改。");
    expect(alert.textContent).not.toContain("hidden-file.csv");
    expect(server.merged.a[0].q).toBe("甲一");
    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();

    fireEvent.click(within(editor()).getByRole("button", { name: "關閉" }));
    await chooseInDialog("捨棄並離開");
    await waitFor(() => expect(screen.queryByRole("heading", { name: "編輯題目" })).toBeNull());
  });

  it("問題空白時停用儲存，切換分類前仍提示草稿未存", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "" } });
    const save = within(editor()).getByRole("button", { name: "儲存" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(server.mergedPuts).toHaveLength(0);

    fireEvent.click(inTree("分類乙"));
    await chooseInDialog("捨棄並離開");
    await screen.findByRole("heading", { name: "分類乙" });
    await editQuestion("乙一");
    expect(server.mergedPuts).toHaveLength(0);
  });

  it("單題刪除要求確認無法復原，取消不寫入，確認才移除目標", async () => {
    await openQuestionA();
    const remove = within(editor()).getByRole("button", { name: "刪除這題" });
    fireEvent.click(remove);

    const dialog = await screen.findByRole("dialog", { name: "刪除題目" });
    expect(dialog.textContent).toContain("刪除後無法復原");
    await chooseInDialog("取消");
    expect(server.mergedPuts).toHaveLength(0);

    fireEvent.click(remove);
    await chooseInDialog("刪除");
    await screen.findByText("已刪除 1 題。");

    expect(server.mergedPuts[0].rows.map((row) => row.q)).toEqual(["甲二", "甲三"]);
    expect(within(table()).queryByRole("button", { name: "甲一" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "編輯題目" })).toBeNull();
  });

  it("拖曳圖片到編輯面板會上傳，使用 API 回傳的類型並儲存圖片", async () => {
    await openQuestionA();
    const file = new File(["image"], "local.png", { type: "image/png" });
    fireEvent.drop(within(editor()).getByText("可把圖片拖到這裡"), {
      dataTransfer: { files: [file] },
    });

    expect(await within(editor()).findByRole("img", { name: "題目的圖片" })).toBeTruthy();
    expect((within(editor()).getByLabelText("圖片類型") as HTMLSelectElement).value).toBe("qr");
    expect(server.imageUploads).toEqual([file]);

    fireEvent.click(within(editor()).getByRole("button", { name: "儲存" }));
    await screen.findByText("已儲存題目。");
    expect(server.merged.a[0].img).toBe("new-image.png");
  });

  it("▶ 測試 送出這一題與語言，未儲存時會先詢問", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "還沒儲存的問題" } });
    const test = within(editor()).getByRole("button", { name: /測試/ });
    fireEvent.click(test);
    await chooseInDialog("取消");
    expect(mocks.openChatTest).not.toHaveBeenCalled();

    fireEvent.click(test);
    await chooseInDialog("捨棄並離開");
    await waitFor(() => expect(mocks.openChatTest).toHaveBeenCalledWith({ question: "甲一", language: "zh" }));
  });
});

describe("搜尋直達", () => {
  it("可搜尋答案並打開指定題目，畫面焦點移到編輯面板", async () => {
    await openPage();
    fireEvent.click(searchFor("乙二的答案").getByRole("button", { name: /乙二/ }));

    expect(await screen.findByDisplayValue("乙二")).toBeTruthy();
    const heading = within(editor()).getByRole("heading", { name: "編輯題目" });
    expect(scrolledTo).toContain(heading);
    expect(document.activeElement).toBe(heading);
    expect(screen.queryByDisplayValue("乙一")).toBeNull();
  });

  it("再搜尋正在編輯的同一題時保留草稿", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "改過的甲一" } });

    fireEvent.click(searchFor("甲一").getByRole("button", { name: /甲一/ }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
  });

  it("由搜尋切到另一題前仍會詢問，取消後原題維持開啟", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "改過的甲一" } });

    fireEvent.click(searchFor("乙二").getByRole("button", { name: /乙二/ }));
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("改過的甲一")).toBeTruthy();
    expect(server.mergedGets).not.toContain("b");

    const result = within(screen.getByRole("list", { name: "題目搜尋結果" }));
    fireEvent.click(result.getByRole("button", { name: /乙二/ }));
    await chooseInDialog("捨棄並離開");
    expect(await screen.findByDisplayValue("乙二")).toBeTruthy();
  });
});

describe("題庫語言、分類及批次工具", () => {
  it("顯示所有語言題數，語言同時篩選分類與表格", async () => {
    await openPage();

    expect(screen.getByRole("button", { name: /全部.*5/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /中文.*3/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /日本語.*0/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /English.*2/ }));
    expect(await screen.findByRole("button", { name: "乙一" })).toBeTruthy();
    expect(within(table()).queryByRole("button", { name: "甲一" })).toBeNull();
    expect(within(sidebar()).queryByText("分類甲")).toBeNull();
    expect(inTree("分類乙")).toBeTruthy();
  });

  it("上層已關閉時，下層分類與題目變灰且保留原開關", async () => {
    server.qaNodes[0].hidden = true;
    server.qaNodes[0].child_ids = ["child"];
    const child = makeNode("child", "子分類", ["子題"], "knowledge/qa/child.csv");
    child.parent_ids = ["a"];
    server.qaNodes[0].children = [child];
    server.merged.child = makeRows(["子題"], "knowledge/qa/child.csv");
    await openPage();
    fireEvent.click(inTree("分類甲"));

    const childLabel = await within(sidebar()).findByText("子分類");
    const childRow = childLabel.closest('[role="treeitem"]')!;
    expect(childRow.className).toMatch(/muted|opacity|subtle|sunken/);
    expect(within(childRow as HTMLElement).getByText("上層已關閉")).toBeTruthy();
    const childDisplay = within(childRow as HTMLElement).getByRole("switch", { name: "前台顯示 子分類" }) as HTMLInputElement;
    expect(childDisplay.disabled).toBe(true);
    expect(childDisplay.checked).toBe(true);

    const questionRow = rowButton("子題").closest('[role="row"]') as HTMLElement;
    expect(questionRow.className).toContain("bg-surface-sunken");
    expect(within(questionRow).getByText("上層已關閉")).toBeTruthy();
    const display = within(questionRow).getByRole("checkbox", { name: "顯示 子題" }) as HTMLInputElement;
    expect(display.disabled).toBe(true);
    expect(display.checked).toBe(true);

    fireEvent.click(within(sidebar()).getByRole("switch", { name: "前台顯示 分類甲" }));
    await waitFor(() => expect(server.categoryWrites).toEqual([{ id: "a", hidden: false }]));
    await waitFor(() => {
      const updatedChild = within(sidebar()).getByRole<HTMLInputElement>("switch", { name: "前台顯示 子分類" });
      const updatedQuestion = within(table()).getByRole<HTMLInputElement>("checkbox", { name: "顯示 子題" });
      expect(updatedChild.disabled).toBe(false);
      expect(updatedChild.checked).toBe(true);
      expect(updatedQuestion.disabled).toBe(false);
      expect(updatedQuestion.checked).toBe(true);
    });
  });

  function selectTwoQuestions() {
    fireEvent.click(within(table()).getByRole("checkbox", { name: "勾選 甲一" }));
    fireEvent.click(within(table()).getByRole("checkbox", { name: "勾選 甲二" }));
    const actions = within(screen.getByRole("group", { name: "題目批次操作" }));
    expect(actions.getByText("已選 2 題")).toBeTruthy();
    return actions;
  }

  it.each([
    { label: "顯示", initial: true, expected: false, notice: "已設為顯示 2 題。" },
    { label: "隱藏", initial: false, expected: true, notice: "已設為隱藏 2 題。" },
  ])("批次$label 依現有 API 寫回選取的題目", async ({ label, initial, expected, notice }) => {
    server.merged.a[0].hidden = initial;
    server.merged.a[1].hidden = initial;
    await openPage();
    expect(screen.queryByRole("group", { name: "題目批次操作" })).toBeNull();

    fireEvent.click(selectTwoQuestions().getByRole("button", { name: label }));
    await screen.findByText(notice);

    expect(server.mergedPuts.map(({ id, baseVersion }) => [id, baseVersion])).toEqual([["a", "base-1"], ["a", "base-1"]]);
    expect(server.merged.a.map((row) => row.hidden)).toEqual([expected, expected, false]);
  });

  it("批次移動一次送出所選題目", async () => {
    await openPage();
    const actions = selectTwoQuestions();
    fireEvent.change(actions.getByLabelText("批次移動的目標分類"), { target: { value: "b" } });
    fireEvent.click(actions.getByRole("button", { name: "移動到分類" }));
    await screen.findByText("已移動 2 題。");

    expect(server.questionMoves).toEqual([
      {
        to_node_id: "b",
        items: [
          { question: "甲一", source_path: "knowledge/qa/a.csv", from_node_ids: ["a"] },
          { question: "甲二", source_path: "knowledge/qa/a.csv", from_node_ids: ["a"] },
        ],
      },
    ]);
    expect(server.entryWrites).toEqual([]);
    expect(server.merged.a.map((row) => row.q)).toEqual(["甲三"]);
  });

  it("批次移動五題只發一次請求，失敗時題庫表格的資料不變", async () => {
    server.qaNodes[0] = makeNode("a", "分類甲", ["甲一", "甲二", "甲三", "甲四", "甲五"], "knowledge/qa/a.csv");
    server.merged.a = makeRows(["甲一", "甲二", "甲三", "甲四", "甲五"], "knowledge/qa/a.csv");
    await openPage();
    for (const q of ["甲一", "甲二", "甲三", "甲四", "甲五"]) {
      fireEvent.click(within(table()).getByRole("checkbox", { name: `勾選 ${q}` }));
    }
    const actions = within(screen.getByRole("group", { name: "題目批次操作" }));
    expect(actions.getByText("已選 5 題")).toBeTruthy();

    server.failMove = { status: 400, detail: "「甲三」在目標分類已經有相同的題目" };
    fireEvent.change(actions.getByLabelText("批次移動的目標分類"), { target: { value: "b" } });
    fireEvent.click(actions.getByRole("button", { name: "移動到分類" }));
    await screen.findByText("「甲三」在目標分類已經有相同的題目");
    expect(server.questionMoves).toHaveLength(1);
    expect(server.questionMoves[0].items).toHaveLength(5);
    expect(server.merged.a.map((row) => row.q)).toEqual(["甲一", "甲二", "甲三", "甲四", "甲五"]);

    server.failMove = undefined;
    fireEvent.click(actions.getByRole("button", { name: "移動到分類" }));
    await screen.findByText("已移動 5 題。");
    expect(server.questionMoves).toHaveLength(2);
    expect(server.questionMoves[1].items).toHaveLength(5);
    expect(server.merged.a).toEqual([]);
  });

  it("批次移動正在編輯的題目前詢問，取消不觸發 API", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "未儲存的甲一" } });
    const actions = selectTwoQuestions();
    fireEvent.change(actions.getByLabelText("批次移動的目標分類"), { target: { value: "b" } });
    fireEvent.click(actions.getByRole("button", { name: "移動到分類" }));
    await chooseInDialog("取消");

    expect(server.entryWrites).toHaveLength(0);
    expect(screen.getByDisplayValue("未儲存的甲一")).toBeTruthy();
  });

  it("批次刪除先確認，再刪除勾選的各題", async () => {
    await openPage();
    fireEvent.click(selectTwoQuestions().getByRole("button", { name: "刪除題目" }));
    const dialog = await screen.findByRole("dialog", { name: "刪除題目" });
    expect(dialog.textContent).toContain("刪除後無法復原");
    await chooseInDialog("刪除");

    await screen.findByText("已刪除 2 題。");
    expect(server.mergedPuts).toHaveLength(2);
    expect(server.merged.a.map((row) => row.q)).toEqual(["甲三"]);
  });

  it("廠商看不到圖譜、維護或文件名稱，但可用匿名標籤開啟文件", async () => {
    mocks.vendor = true;
    await openPage();

    expect(screen.queryByRole("tab", { name: "圖譜" })).toBeNull();
    expect(screen.queryByRole("button", { name: /維護/ })).toBeNull();
    expect(within(sidebar()).queryByText("guide.md")).toBeNull();
    expect(screen.queryByText(/a\.csv|b\.csv/)).toBeNull();

    fireEvent.click(inTree("文件 1"));
    expect(await screen.findByRole("heading", { name: "文件 1" })).toBeTruthy();
    expect(await screen.findByDisplayValue("# 指南內容")).toBeTruthy();
    expect(screen.queryByText(/guide\.md|other\.md/)).toBeNull();
  });
});

describe("文件未儲存的變更", () => {
  it("切換文件前詢問，取消保留草稿", async () => {
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

  it("從文件切到分類前詢問，取消時不關閉文件", async () => {
    await openPage();
    fireEvent.click(inTree("guide.md"));
    fireEvent.change(await screen.findByDisplayValue("# 指南內容"), { target: { value: "# 改過的指南" } });

    fireEvent.click(inTree("分類甲"));
    await chooseInDialog("取消");

    expect(screen.getByDisplayValue("# 改過的指南")).toBeTruthy();
    expect(server.mergedGets).toHaveLength(0);
  });

  it("從問答文件前往題目的分類時只詢問一次", async () => {
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

    expect(await screen.findByRole("heading", { name: /分類甲/ })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});


describe("知識庫新版型審查回歸", () => {
  const save = () => fireEvent.click(within(editor()).getByRole("button", { name: "儲存" }));
  const pick = (name: string) => {
    fireEvent.click(within(table()).getByRole("checkbox", { name: `勾選 ${name}` }));
    return within(screen.getByRole("group", { name: "題目批次操作" }));
  };
  const moveTo = (actions: ReturnType<typeof within>, id: string) => {
    fireEvent.change(actions.getByLabelText("批次移動的目標分類"), { target: { value: id } });
    fireEvent.click(actions.getByRole("button", { name: "移動到分類" }));
  };
  const mount = (id: string, item = server.merged.a[0]) => { server.merged[id].push({ ...item }); };
  const addChild = () => {
    const child = makeNode("child", "子分類", ["子題"], "knowledge/qa/child.csv");
    child.parent_ids = ["a"];
    server.qaNodes[0].child_ids = ["child"];
    server.qaNodes[0].children = [child];
    server.merged.child = makeRows(["子題"], "knowledge/qa/child.csv");
  };

  it("改名後移入已掛載的目標分類，保留目標的題目位置", async () => {
    mount("b");
    server.merged.a[0].also_in = ["分類乙"];
    server.merged.b.unshift(server.merged.b.pop()!);
    fireEvent.change(await openQuestionA(), { target: { value: "改名的甲一" } });
    fireEvent.change(within(editor()).getByLabelText("分類"), { target: { value: "b" } });

    save();

    await screen.findByText("已儲存題目。");
    expect(server.merged.a.map(({ q }) => q)).toEqual(["甲二", "甲三"]);
    expect(server.merged.b.map(({ q }) => q)).toEqual(["改名的甲一", "乙一", "乙二"]);
    expect(server.questionMoves[0].items).toEqual([
      { question: "改名的甲一", source_path: "knowledge/qa/a.csv", from_node_ids: ["a", "b"] },
    ]);
  });

  it("從單一分類批次移動時保留已在目標分類的題目位置", async () => {
    mount("b");
    server.merged.b.unshift(server.merged.b.pop()!);
    await openPage();
    fireEvent.click(inTree("分類甲"));
    pick("甲一");

    moveTo(pick("甲二"), "b");

    await screen.findByText("已移動 2 題。");
    expect(server.merged.a.map(({ q }) => q)).toEqual(["甲三"]);
    expect(server.merged.b.map(({ q }) => q)).toEqual(["甲一", "乙一", "乙二", "甲二"]);
    expect(server.questionMoves[0].items).toEqual([
      { question: "甲一", source_path: "knowledge/qa/a.csv", from_node_ids: ["a", "b"] },
      { question: "甲二", source_path: "knowledge/qa/a.csv", from_node_ids: ["a"] },
    ]);
  });

  it("新增題目寫入面板選定的分類", async () => {
    await openPage();
    fireEvent.click(inTree("分類甲"));
    fireEvent.click(screen.getByRole("button", { name: "新增一題" }));
    const panel = within(screen.getByRole("complementary", { name: "新增題目" }));
    fireEvent.change(panel.getByLabelText("問題"), { target: { value: "新問題" } });
    fireEvent.change(panel.getByLabelText("答案"), { target: { value: "新答案" } });
    fireEvent.change(panel.getByLabelText("分類"), { target: { value: "b" } });
    fireEvent.click(panel.getByRole("button", { name: "儲存" }));
    await screen.findByText("已儲存題目。");
    expect(server.mergedPuts.map(({ id }) => id)).toEqual(["b"]);
    expect(server.merged.b.at(-1)).toMatchObject({ q: "新問題", source_file: "knowledge/qa/manual_b.md" });
  });

  it.each(["新的圖片.png", ""])("答覆存檔保留剛讀到的圖片（%s）", async (image) => {
    server.merged.a[0].img = "過期圖片.png";
    await openPage();
    server.merged.a[0].img = image;
    await editQuestion("甲一");
    fireEvent.change(within(editor()).getByLabelText("答案"), { target: { value: "更新答案" } });
    save();
    await screen.findByText("已儲存題目。");
    expect(server.mergedPuts[0].rows[0].img).toBe(image);
  });

  it("單一分類可只解除目前掛載，保留來源和其他分類", async () => {
    mount("b");
    await openPage();
    fireEvent.click(inTree("分類乙"));
    await editQuestion("甲一");
    fireEvent.click(within(editor()).getByRole("button", { name: "從這個分類移除" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toMatch(/1 個分類.*保留來源文件/);
    await chooseInDialog("從這個分類移除");
    await screen.findByText("已從這個分類移除 1 題。");
    expect(server.entryWrites).toEqual([{ id: "b", method: "DELETE", question: "甲一", sourcePath: "knowledge/qa/a.csv" }]);
    expect(server.merged.a[0].q).toBe("甲一");
    expect(server.mergedPuts).toEqual([]);
  });

  it("永久刪除前讀取最新掛載，確認後從所有分類與來源刪除", async () => {
    await openQuestionA();
    mount("b");
    fireEvent.click(within(editor()).getByRole("button", { name: /刪除/ }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toMatch(/2 個分類.*從來源文件刪除 1 題/);
    await chooseInDialog("刪除");
    await screen.findByText("已刪除 1 題。");
    expect(server.entryWrites).toMatchObject([{ id: "b", method: "DELETE", question: "甲一" }]);
    expect(server.mergedPuts[0]).toMatchObject({ id: "a" });
    expect(server.merged.a.some(({ q }) => q === "甲一")).toBe(false);
    expect(server.merged.b.some(({ q }) => q === "甲一")).toBe(false);
  });

  it("永久刪除確認期間掛載增加時，先更新確認範圍", async () => {
    await openQuestionA();
    fireEvent.click(within(editor()).getByRole("button", { name: /刪除/ }));
    const dialog = await screen.findByRole("dialog");
    mount("b");
    fireEvent.click(within(dialog).getByRole("button", { name: "刪除" }));
    await waitFor(() => expect(dialog.textContent).toContain("2 個分類"));
    expect(server.entryWrites).toEqual([]);
    expect(server.mergedPuts).toEqual([]);
  });

  it("可以把同一題也放到另一分類，保留原掛載", async () => {
    await openQuestionA();
    fireEvent.click(within(editor()).getByRole("button", { name: "也放到其他分類" }));
    const dialog = await screen.findByRole("dialog", { name: /也放到/ });
    fireEvent.click(within(dialog).getByRole("radio", { name: "分類乙" }));
    await chooseInDialog("放到這裡");
    expect(server.entryWrites).toEqual([{ id: "b", method: "POST", question: "甲一", sourcePath: "knowledge/qa/a.csv" }]);
    expect(server.merged.a[0].q).toBe("甲一");
  });

  it("寫入成功但分類樹重抓失敗時，仍回報存檔成功並提示重新整理", async () => {
    fireEvent.change(await openQuestionA(), { target: { value: "已寫入的甲一" } });
    server.failTreeRefresh = true;
    save();
    await screen.findByText("已儲存題目。");
    await screen.findByText("資料已儲存，畫面更新失敗，請重新整理");
    expect(server.merged.a[0].q).toBe("已寫入的甲一");
    expect(screen.queryByRole("heading", { name: "編輯題目" })).toBeNull();
  });

  it.each([
    { status: 409, detail: "這個分類在你編輯時被改過了，請重新載入後再存檔", notice: "有人同時修改了題目，請重新整理後再改。" },
    { status: 400, detail: "選單專用的題目沒有固定答案，要有答案請把題目放進文件，未做任何變更", notice: /選單專用的題目沒有固定答案/ },
  ])("顯示 HTTP $status 對應的儲存訊息", async ({ status, detail, notice }) => {
    fireEvent.change(await openQuestionA(), { target: { value: "我的草稿" } });
    server.saveRejection = { status, detail };
    save();
    await within(editor()).findByText(notice);
    expect(screen.getByDisplayValue("我的草稿")).toBeTruthy();
  });

  it("批次移動在樹重抓失敗時仍計入移動成功的題目", async () => {
    await openPage();
    const actions = pick("甲一");
    server.failTreeRefresh = true;
    moveTo(actions, "b");
    await screen.findByText("已移動 1 題。");
    expect(server.merged.a.some(({ q }) => q === "甲一")).toBe(false);
    expect(server.merged.b.some(({ q }) => q === "甲一")).toBe(true);
  });

  it("批次移動失敗時整批不變並顯示錯誤", async () => {
    await openPage();
    pick("乙一");
    const actions = pick("甲一");
    server.refuseDetach = "a";
    moveTo(actions, "b");
    await screen.findByRole("alert");
    expect(server.questionMoves).toHaveLength(1);
    expect(server.merged.a.some(({ q }) => q === "甲一")).toBe(true);
    expect(server.merged.b.some(({ q }) => q === "甲一")).toBe(false);
  });

  it("圖片類型只顯示伺服器值，停用手動欄位且存檔不再寫入瀏覽器", async () => {
    Object.assign(server.merged.a[0], { img: "saved.png", image_kind: "qr" });
    writeScoped("kb-image-kinds:default", JSON.stringify({ "saved.png": "" }));
    const storage = vi.spyOn(Storage.prototype, "setItem");
    await openQuestionA();
    const imageKind = within(editor()).getByLabelText("圖片類型") as HTMLSelectElement;
    expect(imageKind.disabled).toBe(true);
    expect(imageKind.value).toBe("qr");
    expect(within(editor()).getByText(/之後開放/)).toBeTruthy();
    expect(within(rowButton("甲一").closest("tr")!).getByText("QR")).toBeTruthy();
    save();
    await screen.findByText("已儲存題目。");
    expect(storage.mock.calls.some(([key]) => key.includes("kb-image-kinds:"))).toBe(false);
  });

  it.each(["顯示", "隱藏"])("批次%s 略過上層關閉的題目並說明原因", async (label) => {
    server.qaNodes[0].hidden = true;
    addChild();
    server.merged.child[0].hidden = label === "顯示";
    server.merged.b[0].hidden = label === "顯示";
    await openPage();
    pick("乙一");
    const actions = pick("子題");
    expect(within(table()).getByRole<HTMLInputElement>("checkbox", { name: "顯示 子題" }).disabled).toBe(true);
    fireEvent.click(actions.getByRole("button", { name: label }));
    await screen.findByText(/略過 1 題.*上層已關閉/);
    expect(server.mergedPuts.map(({ id }) => id)).toEqual(["b"]);
    expect(server.merged.child[0].hidden).toBe(label === "顯示");
  });

  it("分類自己的關閉狀態在表格和面板照實標示", async () => {
    server.qaNodes[0].hidden = true;
    await openQuestionA();
    expect(within(rowButton("甲一").closest("tr")!).getByText("分類已關閉")).toBeTruthy();
    expect(within(editor()).getByText(/分類已關閉/)).toBeTruthy();
  });

  describe("全部分類批次移動放在好幾個分類的題目", () => {
    const setup = async () => {
      mount("b");
      server.qaNodes.push(makeNode("c", "分類丙", [], ""));
      server.merged.c = [];
      await openPage();
      pick("乙二");
      moveTo(pick("甲一"), "c");
      return screen.findByRole("dialog", { name: "這些題目放在好幾個分類" });
    };

    it("先列出會被移出的分類，選擇前不寫入", async () => {
      const dialog = await setup();
      expect(dialog.textContent).toContain("甲一：會移出 分類甲、分類乙");
      expect(dialog.textContent).toContain("另外 1 題只放在一個分類");
      expect(server.entryWrites).toEqual([]);
      expect(server.mergedPuts).toEqual([]);
    });

    it("移出原本所有分類：多分類題目只留在新分類，單一分類題目直接移動", async () => {
      await setup();
      await chooseInDialog("移出原本所有分類");
      await screen.findByText("已移動 2 題。");
      expect(server.questionMoves).toEqual([
        {
          to_node_id: "c",
          items: [
            { question: "甲一", source_path: "knowledge/qa/a.csv", from_node_ids: ["a", "b"] },
            { question: "乙二", source_path: "knowledge/qa/b.csv", from_node_ids: ["b"] },
          ],
        },
      ]);
    });

    it("只加入新分類：保留原本的分類，另外回報", async () => {
      await setup();
      await chooseInDialog("只加入新分類（保留原本的）");
      await screen.findByText("已移動 1 題，已加入新分類並保留原本分類 1 題。");
      expect(server.questionMoves).toEqual([
        {
          to_node_id: "c",
          items: [
            { question: "甲一", source_path: "knowledge/qa/a.csv", from_node_ids: [] },
            { question: "乙二", source_path: "knowledge/qa/b.csv", from_node_ids: ["b"] },
          ],
        },
      ]);
      expect(server.merged.a.some(({ q }) => q === "甲一")).toBe(true);
      expect(server.merged.b.some(({ q }) => q === "甲一")).toBe(true);
    });

    it("取消不寫入任何資料", async () => {
      await setup();
      await chooseInDialog("取消");
      expect(server.questionMoves).toEqual([]);
      expect(server.mergedPuts).toEqual([]);
    });

    it("確認前分類又變了，重新列出範圍，不移出沒列出的分類", async () => {
      const dialog = await setup();
      server.qaNodes.push(makeNode("d", "分類丁", [], ""));
      server.merged.d = [{ ...server.merged.a[0] }];
      fireEvent.click(within(dialog).getByRole("button", { name: "移出原本所有分類" }));
      await waitFor(() => expect(dialog.textContent).toContain("剛剛有變更"));
      expect(dialog.textContent).toContain("分類甲、分類乙、分類丁");
      expect(server.questionMoves).toEqual([]);
    });
  });

  describe("改分類時移動失敗，內容已存", () => {
    const failMove = async (question: string) => {
      server.refuseDetach = "a";
      fireEvent.change(within(editor()).getByLabelText("問題"), { target: { value: question } });
      fireEvent.change(within(editor()).getByLabelText("答案"), { target: { value: "新的答案" } });
      fireEvent.change(within(editor()).getByLabelText("分類"), { target: { value: "b" } });
      save();
      await within(editor()).findByText(/題目內容已儲存，但移動分類未完成/);
      expect(server.mergedPuts).toHaveLength(1);
      server.refuseDetach = undefined;
      save();
      await screen.findByText("已儲存題目。");
    };

    it.each(["甲一", "改名的甲一"])("重按儲存只重試移動分類，不誤報衝突（%s）", async (question) => {
      await openQuestionA();
      await failMove(question);
      expect(screen.queryByText(/有人同時修改/)).toBeNull();
      expect(server.mergedPuts).toHaveLength(1);
      expect(server.questionMoves).toEqual([
        {
          to_node_id: "b",
          items: [{ question, source_path: "knowledge/qa/a.csv", from_node_ids: ["a"] }],
        },
        {
          to_node_id: "b",
          items: [{ question, source_path: "knowledge/qa/a.csv", from_node_ids: ["a"] }],
        },
      ]);
      expect(server.merged.a.some(({ q }) => q === question)).toBe(false);
      expect(server.merged.b.find(({ q }) => q === question)?.a).toBe("新的答案");
    });
  });

  describe("未分類題目直接編輯與掛上分類", () => {
    beforeEach(() => {
      server.uncategorized = [
        {
          index: "1",
          q: "未分類題目",
          a: "原本的未分類答案",
          img: "",
          url: "",
          source_file: "knowledge/qa/off.csv",
          hidden: false,
          original_q: "未分類題目",
          base_version: "hash-off-1",
        },
      ];
    });

    it("未分類題目可編輯問題、答案、網址、顯示與圖片並直接存檔，保留開啟來源文件按鈕", async () => {
      await openPage();
      await editQuestion("未分類題目");
      const panel = within(editor());
      expect(panel.getByRole("button", { name: "開啟來源文件" })).toBeTruthy();
      expect(panel.queryByRole("button", { name: "刪除這題" })).toBeNull();

      fireEvent.change(panel.getByLabelText("問題"), { target: { value: "改過的未分類題目" } });
      fireEvent.change(panel.getByLabelText("答案"), { target: { value: "改過的未分類答案" } });
      fireEvent.change(panel.getByLabelText("網址"), { target: { value: "https://example.com/off" } });
      fireEvent.click(panel.getByLabelText("前台顯示"));
      const file = new File(["image"], "off.png", { type: "image/png" });
      fireEvent.drop(panel.getByText("可把圖片拖到這裡"), { dataTransfer: { files: [file] } });
      await panel.findByRole("img", { name: "題目的圖片" });

      save();
      await screen.findByText("已儲存題目。");

      expect(server.questionPuts).toEqual([
        {
          project_id: "default",
          source_path: "knowledge/qa/off.csv",
          original_q: "未分類題目",
          q: "改過的未分類題目",
          a: "改過的未分類答案",
          img: "new-image.png",
          url: "https://example.com/off",
          hidden: true,
          base_hash: "hash-off-1",
        },
      ]);
      expect(server.questionMoves).toEqual([]);
      expect(rowButton("改過的未分類題目")).toBeTruthy();
    });

    it("未分類題目選了分類時先送內容再送移動，第二步失敗顯示部分成功訊息且重試只補移動", async () => {
      await openPage();
      await editQuestion("未分類題目");
      const panel = within(editor());
      fireEvent.change(panel.getByLabelText("問題"), { target: { value: "準備歸類的題目" } });
      fireEvent.change(panel.getByLabelText("答案"), { target: { value: "準備歸類的答案" } });
      fireEvent.change(panel.getByLabelText("分類"), { target: { value: "b" } });
      server.failMove = { status: 503, detail: "暫時無法放進分類" };

      save();
      await panel.findByText(/題目內容已儲存，但放進分類未完成/);
      expect(server.questionPuts).toHaveLength(1);
      expect(server.questionMoves).toEqual([
        {
          to_node_id: "b",
          items: [{ question: "準備歸類的題目", source_path: "knowledge/qa/off.csv", from_node_ids: [] }],
        },
      ]);

      server.failMove = undefined;
      save();
      await screen.findByText("已儲存題目。");
      expect(server.questionPuts).toHaveLength(1);
      expect(server.questionMoves).toHaveLength(2);
      expect(server.merged.b.some(({ q }) => q === "準備歸類的題目")).toBe(true);
    });

    it("未分類題目存檔遇 409 時顯示衝突訊息並重新載入清單", async () => {
      await openPage();
      await editQuestion("未分類題目");
      const panel = within(editor());
      fireEvent.change(panel.getByLabelText("答案"), { target: { value: "衝突的草稿" } });
      server.failSave = true;
      const beforeGets = server.questionListGets;

      save();
      await panel.findByText("有人同時修改了題目，請重新整理後再改。");
      await waitFor(() => expect(server.questionListGets).toBeGreaterThan(beforeGets));
    });

    it("未分類題目沒有答案時，只選分類也能掛載", async () => {
      server.uncategorized[0].a = "";
      await openPage();
      await editQuestion("未分類題目");
      fireEvent.change(within(editor()).getByLabelText("分類"), { target: { value: "b" } });

      save();

      await screen.findByText("已儲存題目。");
      expect(server.uncategorized).toEqual([]);
      expect(server.merged.b.find(({ q }) => q === "未分類題目")?.a).toBe("");
    });

    it.each(["請指定來源文件", "SOUL.md 不是知識庫文件", "knowledge/notes.md 不是 QA 文件"])(
      "單題儲存顯示來源驗證錯誤（%s）",
      async (detail) => {
        await openPage();
        await editQuestion("未分類題目");
        const panel = within(editor());
        fireEvent.change(panel.getByLabelText("答案"), { target: { value: "新答案" } });
        server.saveRejection = { status: 400, detail };

        save();

        expect((await panel.findByRole("alert")).textContent).toBe(detail);
        expect(server.uncategorized[0].a).toBe("原本的未分類答案");
      },
    );

    it("只選分類時顯示移動路由的來源錯誤", async () => {
      await openPage();
      await editQuestion("未分類題目");
      const panel = within(editor());
      fireEvent.change(panel.getByLabelText("分類"), { target: { value: "b" } });
      const detail = "「未分類題目」沒有指定來源文件";
      server.failMove = { status: 400, detail };

      save();

      expect((await panel.findByRole("alert")).textContent).toBe(detail);
      expect(server.uncategorized[0].q).toBe("未分類題目");
    });
  });
});
