import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { QaAllQuestions } from "../api/knowledge";
import { question } from "../components/kb/questions/fixtures";
import { NavigationGuardProvider } from "../context/NavigationGuardContext";
import KnowledgeBase from "./KnowledgeBase";

// 這裡不 mock 任何 hook，只換掉網路：要鎖住的是「上傳後不用重新整理就看得到結果」，
// 這件事橫跨匯入、文件清單、快速問答三個 hook，分開測看不出來有沒有接好。

vi.mock("../context/NavigationContext", () => ({
  useNavigation: () => ({ currentSubView: undefined, navigateTo: vi.fn() }),
}));

vi.mock("../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "default" }),
}));

const auth = vi.hoisted(() => ({
  account: { id: "admin", username: "admin", role: "admin", disabled: false, created_at: "" } as Record<string, unknown>,
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: auth.account }),
}));

const ADMIN_ACCOUNT = { ...auth.account };

interface ServerState {
  documents: Array<Record<string, unknown>>;
  qaNodes: Array<Record<string, unknown>>;
  questionBank: QaAllQuestions;
  pending: Array<Record<string, unknown>>;
  job: Record<string, unknown>;
  uploadPaths: string[];
  previews: Record<string, unknown>;
  previewError?: string;
  commitBodies: Array<Record<string, unknown>>;
}

const IDLE_JOB = {
  state: "idle",
  started_at: null,
  finished_at: null,
  files: {},
  committed: [],
  skipped: [],
  results: {},
  skip_reasons: {},
  error: null,
};

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
  const { pathname } = new URL(url, "http://localhost");
  const method = init?.method ?? "GET";
  if (pathname.endsWith("/uploads/limits")) return ok({ document_max_upload_bytes: 1024 * 1024 });
  if (pathname.endsWith("/knowledge/base/documents")) {
    return ok({ documents: server.documents, document_count: server.documents.length, directories: [] });
  }
  if (pathname.endsWith("/knowledge/settings")) return ok({ language_routes: ["zh"] });
  if (pathname.endsWith("/knowledge/qa/nodes")) return ok(server.qaNodes);
  if (pathname.endsWith("/knowledge/qa/questions")) return ok(server.questionBank);
  if (pathname.endsWith("/knowledge/qa/nodes/qa_node_1/merged")) {
    return ok(server.questionBank.questions.map((item) => ({
      original_q: item.question,
      q: item.question,
      a: item.answer,
      source_file: item.source.path,
      base_version: "version-1",
    })));
  }
  if (pathname.endsWith("/knowledge/raw/pending")) return ok({ files: server.pending });
  if (pathname.endsWith("/knowledge/raw/commit/status")) return ok(server.job);
  if (pathname.endsWith("/knowledge/raw/upload") && method === "POST") {
    return ok({ status: "ok", files: server.uploadPaths.map((path) => ({ path })) });
  }
  if (pathname.endsWith("/knowledge/raw/preview") && method === "POST") {
    if (server.previewError) {
      return { ...ok({ detail: server.previewError }), ok: false, status: 503 } as Response;
    }
    const { paths } = JSON.parse(init?.body as string) as { paths: string[] };
    return ok({ files: Object.fromEntries(paths.map((path) => [path, server.previews[path] ?? { kind: "document" }])) });
  }
  if (pathname.endsWith("/knowledge/raw/commit") && method === "POST") {
    server.commitBodies.push(JSON.parse(init?.body as string));
    return ok({ status: "started", project_id: "default", job: server.job });
  }
  throw new Error(`unexpected request: ${method} ${pathname}`);
}

async function advance(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function openPage() {
  render(
    <NavigationGuardProvider>
      <KnowledgeBase />
    </NavigationGuardProvider>,
  );
  await advance();
}

function showUpload() {
  fireEvent.click(screen.getByRole("button", { name: "上傳" }));
}

function pickFile(name: string) {
  fireEvent.change(screen.getByTestId("knowledge-upload-input"), {
    target: { files: [new File(["x"], name)] },
  });
}

const makeDocument = (overrides: Record<string, unknown> = {}) => ({
  path: "knowledge/guide.md",
  title: "guide",
  category: "knowledge",
  extension: ".md",
  size: 10,
  updated_at: "2026-11-05T10:00:00",
  is_core: false,
  is_indexable: true,
  is_indexed: false,
  preview: "",
  source_type: "upload",
  source_url: null,
  enabled: true,
  created_at: "2026-11-05T10:00:00",
  language: "zh",
  ...overrides,
});

beforeEach(() => {
  auth.account = { ...ADMIN_ACCOUNT };
  vi.useFakeTimers();
  window.localStorage.clear();
  sessionStorage.clear();
  server = {
    documents: [],
    qaNodes: [],
    questionBank: { categories: [], questions: [] },
    pending: [],
    job: IDLE_JOB,
    uploadPaths: [],
    previews: {},
    commitBodies: [],
  };
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => route(String(input), init));
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("KnowledgeBase import, end to end", () => {
  it("shows a QA table in the results and in the tree without reloading the page", async () => {
    await openPage();
    expect(screen.getByText(/還沒有題目/)).toBeTruthy();
    expect(screen.getByText("還沒有文件")).toBeTruthy();
    showUpload();

    server.uploadPaths = ["raw/booth_faq_en.csv"];
    server.previews = {
      "booth_faq_en.csv": {
        kind: "qa",
        target: "knowledge/qa/booth_faq_en.md",
        existing: false,
        errors: [],
        duplicate_rows: 0,
        questions: [
          { question: "Q1", status: "new", placement: ["booth_faq_en"], language: "en" },
          { question: "Q2", status: "new", placement: ["booth_faq_en"], language: "en" },
        ],
        missing_images: [],
        notes: [],
      },
    };
    server.job = {
      ...IDLE_JOB,
      state: "running",
      started_at: "t1",
      files: { "booth_faq_en.csv": "pending" },
    };
    pickFile("booth_faq_en.csv");
    await advance();

    // 上傳問答表後先顯示檢查畫面與摘要，確認按「匯入」才送出 commit
    const reviewRegion = screen.getByRole("region", { name: "匯入前檢查" });
    expect(within(reviewRegion).getByText("新題目 2、重複（答案相同）0、重複（答案不同）0、檔案內重複 0、格式錯誤 0")).toBeTruthy();
    expect(server.commitBodies).toEqual([]);

    fireEvent.click(within(reviewRegion).getByRole("button", { name: "匯入" }));
    await advance();

    expect(server.commitBodies).toEqual([{
      project_id: "default",
      paths: ["booth_faq_en.csv"],
      normalize: false,
      decisions: {
        "booth_faq_en.csv": {
          conflicts: {},
          images: {},
        },
      },
    }]);
    expect(screen.getByRole("button", { name: "匯入中 0/1" })).toBeTruthy();
    expect(screen.getByText("排隊中")).toBeTruthy();

    const node = {
      node_id: "qa_node_1",
      label: "booth_faq_en",
      parent_ids: [],
      child_ids: [],
      order: 1,
      hidden: false,
      qa_entries: [
        { question: "Q1", source_path: "knowledge/qa/booth_faq_en.md", hidden: false, image_id: null },
        { question: "Q2", source_path: "knowledge/qa/booth_faq_en.md", hidden: false, image_id: null },
      ],
      children: [],
    };
    server.qaNodes = [node];
    server.questionBank = {
      categories: [{
        node_id: node.node_id,
        label: node.label,
        path: [node.label],
        parent_id: null,
        hidden: false,
      }],
      questions: node.qa_entries.map((entry, index) => question({
        id: entry.question,
        question: entry.question,
        answer: `Imported answer ${index + 1}`,
        language: "en",
        source: { kind: "file", path: entry.source_path, label: "booth_faq_en.md" },
        category_ids: [node.node_id],
      })),
    };
    server.documents = [makeDocument({ path: "knowledge/qa/booth_faq_en.md", source_type: "qa", is_indexed: true })];
    server.job = {
      ...server.job,
      state: "done",
      files: { "booth_faq_en.csv": "committed" },
      results: {
        "booth_faq_en.csv": {
          target: "knowledge/qa/booth_faq_en.md",
          kind: "qa",
          language: "en",
          updated: false,
          qa_node_id: "qa_node_1",
          qa_node_label: "booth_faq_en",
          question_count: 2,
        },
      },
    };
    await advance(2000);

    expect(screen.getByText("已放進快速問答：booth_faq_en（2 題）")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /匯入中/ })).toBeNull();
    expect(screen.getByText("1 份文件")).toBeTruthy();
    const tree = screen.getByRole("tree", { name: "知識庫目錄" });
    expect(within(tree).getByRole("treeitem", { name: /^booth_faq_en/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "查看 booth_faq_en.csv" }));
    expect(screen.getByRole("heading", { name: "booth_faq_en" })).toBeTruthy();
    const table = screen.getByRole("table", { name: "題庫表格" });
    expect(within(table).getByRole("button", { name: "Q1" })).toBeTruthy();
    expect(within(table).getByRole("button", { name: "Q2" })).toBeTruthy();
    fireEvent.click(within(table).getByRole("button", { name: "Q1" }));
    await advance();
    expect((screen.getByLabelText("答案") as HTMLTextAreaElement).value).toBe("Imported answer 1");

    // 結果留著：回到新增資料畫面還看得到。
    showUpload();
    await advance();
    expect(screen.getByText("已放進快速問答：booth_faq_en（2 題）")).toBeTruthy();
  });

  it("uploads an ordinary document without review and follows it until searchable", async () => {
    await openPage();
    showUpload();

    server.uploadPaths = ["raw/guide.docx"];
    server.documents = [makeDocument()];
    server.job = {
      ...IDLE_JOB,
      state: "done",
      started_at: "t1",
      files: { "guide.docx": "committed" },
      results: {
        "guide.docx": { target: "knowledge/guide.md", kind: "document", language: "zh", updated: false },
      },
    };
    pickFile("guide.docx");
    await advance();

    expect(screen.queryByRole("region", { name: "匯入前檢查" })).toBeNull();
    expect(server.commitBodies[0].paths).toEqual(["guide.docx"]);
    expect(screen.getByText("已加入知識庫，內容未經 AI 修改")).toBeTruthy();
    expect(screen.getByText("1 份文件 · 1 份處理中")).toBeTruthy();

    server.documents = [makeDocument({ is_indexed: true })];
    await advance(3000);

    expect(screen.getByText("1 份文件")).toBeTruthy();
    expect(screen.queryByText(/份處理中/)).toBeNull();
  });

  it("offers files left behind without importing them along with a new upload", async () => {
    server.pending = [{ path: "old.md", size: 5, updated_at: "2026-11-01T10:00:00" }];
    await openPage();
    showUpload();
    expect(screen.getByText("有 1 個之前上傳、還沒匯入的檔案")).toBeTruthy();

    server.uploadPaths = ["raw/new.md"];
    server.job = {
      ...IDLE_JOB,
      state: "running",
      started_at: "t1",
      files: { "new.md": "pending" },
    };
    pickFile("new.md");
    await advance();

    expect(server.commitBodies[0].paths).toEqual(["new.md"]);
    expect(screen.getByText("有 1 個之前上傳、還沒匯入的檔案")).toBeTruthy();
  });

  it("leaves a staged file in the waiting area on preview failure and offers review on retry", async () => {
    await openPage();
    showUpload();
    server.uploadPaths = ["raw/faq.csv"];
    server.previewError = "伺服器暫時無法檢查";
    pickFile("faq.csv");
    await advance();

    expect(screen.getByText(/檢查檔案失敗：伺服器暫時無法檢查.*檔案已留在等待匯入區/)).toBeTruthy();
    expect(screen.getByText("有 1 個之前上傳、還沒匯入的檔案")).toBeTruthy();
    expect(server.commitBodies).toEqual([]);

    server.previewError = undefined;
    server.previews = {
      "faq.csv": {
        kind: "qa", target: "knowledge/qa/faq.md", existing: false,
        errors: [], duplicate_rows: 0, missing_images: [], notes: [],
        questions: [{ question: "營業時間", status: "new", placement: ["faq"] }],
      },
    };
    fireEvent.click(screen.getByRole("button", { name: "全部匯入" }));
    await advance();
    expect(screen.getByRole("region", { name: "匯入前檢查" })).toBeTruthy();
    expect(server.commitBodies).toEqual([]);
  });

  it("shows a vendor the masked name of an existing category in the review, not a new one", async () => {
    auth.account = {
      id: "vendor-1", username: "vendor", role: "user", disabled: false, created_at: "",
      vendor_name: "合作廠商",
    };
    const source = "knowledge/qa/faq.md";
    server.documents = [makeDocument({ path: source, title: "faq", source_type: "qa" })];
    server.qaNodes = [{
      node_id: "zh", label: "中文", parent_ids: [], child_ids: ["qa_faq"], order: 1, hidden: false,
      qa_entries: [],
      children: [{
        node_id: "qa_faq", label: "faq", parent_ids: ["zh"], child_ids: [], order: 1, hidden: false,
        qa_entries: [{ question: "營業時間", source_path: source, hidden: false, image_id: null }],
        children: [],
      }],
    }];
    server.pending = [{ path: "faq.csv", size: 10, updated_at: "2026-11-20T18:00:00" }];
    server.previews = {
      "faq.csv": {
        kind: "qa", target: source, existing: true, errors: [], duplicate_rows: 0,
        questions: [{ question: "營業時間", status: "same", placement: ["中文", "faq"], language: "zh" }],
        missing_images: [], notes: [],
      },
    };
    await openPage();
    showUpload();
    fireEvent.click(screen.getByRole("button", { name: "全部匯入" }));
    await advance();

    const placement = screen.getByRole("list", { name: "問答表 1 分類預覽" });
    expect(within(placement).getByText("文件 1的題目")).toBeTruthy();
    expect(within(placement).queryByText("faq")).toBeNull();
    expect(within(placement).queryByText("新")).toBeNull();
  });

  it("reviews a waiting QA table and opens the original question beside the deferred answer", async () => {
    const rawPath = "faq.csv";
    const source = "knowledge/qa/faq.md";
    const origin = "archive/originals/faq.csv";
    const name = "門票費用";
    server.pending = [{ path: rawPath, size: 10, updated_at: "2026-11-20T18:00:00" }];
    server.previews = {
      [rawPath]: {
        kind: "qa", target: source, existing: true, errors: [], duplicate_rows: 0,
        questions: [{
          question: name, status: "conflict", placement: ["服務"],
          old: { answer: "原本 100 元" }, new: { answer: "週末改為 150 元" },
        }],
        missing_images: [], notes: [],
      },
    };
    server.questionBank = {
      categories: [{ node_id: "qa_node_1", label: "服務", path: ["服務"], parent_id: null, hidden: false }],
      questions: [
        question({ id: "other", question: name, answer: "另一份文件的答案", source: { kind: "file", path: "knowledge/qa/other.md", label: "其他" }, category_ids: ["qa_node_1"] }),
        question({ id: "original", question: name, answer: "原本 100 元", source: { kind: "file", path: source, label: "服務" }, category_ids: ["qa_node_1"] }),
      ],
    };
    await openPage();
    showUpload();
    fireEvent.click(screen.getByRole("button", { name: "全部匯入" }));
    await advance();

    const review = screen.getByRole("region", { name: "匯入前檢查" });
    expect(server.commitBodies).toEqual([]);
    fireEvent.click(within(review).getByRole("radio", { name: "稍後調整" }));
    server.pending = [];
    server.job = {
      ...IDLE_JOB, state: "done", started_at: "t1",
      files: { [rawPath]: "committed" },
      results: {
        [rawPath]: {
          kind: "qa", target: source, updated: true,
          later: [{ question: name, answer: "週末改為 150 元" }], origin_path: origin,
        },
      },
    };
    fireEvent.click(within(review).getByRole("button", { name: "匯入" }));
    await advance();

    expect(server.commitBodies[0].decisions).toEqual({ [rawPath]: { conflicts: { [name]: "later" }, images: {} } });
    expect(screen.getByText(`原始上傳檔案：${origin}`)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name }));
    await advance();

    const editor = screen.getByRole("complementary", { name: "編輯題目" });
    expect(within(editor).getByLabelText<HTMLTextAreaElement>("答案").value).toBe("原本 100 元");
    const reference = screen.getByRole("complementary", { name: "新檔案的答案" });
    expect(within(reference).getByText("週末改為 150 元")).toBeTruthy();
    fireEvent.click(within(editor).getByRole("button", { name: "關閉" }));
    expect(screen.queryByRole("complementary", { name: "新檔案的答案" })).toBeNull();
  });
});
