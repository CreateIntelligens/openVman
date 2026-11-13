import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ account: { id: "admin", username: "admin", role: "admin", disabled: false, created_at: "" } }),
}));

vi.mock("../components/kb/qa/MergedCsvPane", () => ({
  default: ({ nodeId, nodeLabel }: { nodeId: string | null; nodeLabel?: string }) => (
    <div data-testid="merged-qa-pane">{nodeId}:{nodeLabel}</div>
  ),
}));

interface ServerState {
  documents: Array<Record<string, unknown>>;
  qaNodes: Array<Record<string, unknown>>;
  pending: Array<Record<string, unknown>>;
  job: Record<string, unknown>;
  uploadPaths: string[];
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
  if (pathname.endsWith("/knowledge/raw/pending")) return ok({ files: server.pending });
  if (pathname.endsWith("/knowledge/raw/commit/status")) return ok(server.job);
  if (pathname.endsWith("/knowledge/raw/upload") && method === "POST") {
    return ok({ status: "ok", files: server.uploadPaths.map((path) => ({ path })) });
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
  vi.useFakeTimers();
  window.localStorage.clear();
  sessionStorage.clear();
  server = {
    documents: [],
    qaNodes: [],
    pending: [],
    job: IDLE_JOB,
    uploadPaths: [],
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
    expect(screen.getByText(/知識庫還沒有資料/)).toBeTruthy();
    expect(screen.getByText("還沒有文件")).toBeTruthy();

    server.uploadPaths = ["raw/booth_faq_en.csv"];
    server.job = {
      ...IDLE_JOB,
      state: "running",
      started_at: "t1",
      files: { "booth_faq_en.csv": "pending" },
    };
    pickFile("booth_faq_en.csv");
    await advance();

    expect(server.commitBodies).toEqual([{
      project_id: "default",
      paths: ["booth_faq_en.csv"],
      normalize: false,
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
    expect(screen.getByTestId("merged-qa-pane").textContent).toBe("qa_node_1:booth_faq_en");

    // 結果留著：回到新增資料畫面還看得到。
    fireEvent.click(screen.getByRole("button", { name: "新增資料" }));
    await advance();
    expect(screen.getByText("已放進快速問答：booth_faq_en（2 題）")).toBeTruthy();
  });

  it("follows a document from processing to searchable without reloading the page", async () => {
    await openPage();

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
});
