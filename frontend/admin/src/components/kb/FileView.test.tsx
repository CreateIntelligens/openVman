import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeDocument } from "../../api";
import FileView from "./FileView";

const baseDocument: KnowledgeDocument = {
  path: "knowledge/faq.md",
  title: "FAQ",
  category: "knowledge",
  extension: ".md",
  size: 42,
  updated_at: "2026-07-01T00:00:00Z",
  is_core: false,
  is_indexable: true,
  is_indexed: true,
  preview: "",
  source_type: "qa",
  source_url: null,
  enabled: true,
  created_at: "2026-07-01T00:00:00Z",
  content: "## Q1\n\nA1",
};

const uploadedDocument: KnowledgeDocument = {
  ...baseDocument,
  source_type: "upload",
  content: "# 門市資訊\n\n週一公休",
};

function renderFileView(overrides: Partial<Parameters<typeof FileView>[0]> = {}) {
  const props = {
    document: baseDocument,
    editContent: overrides.document?.content ?? baseDocument.content,
    setEditContent: vi.fn(),
    loading: false,
    saving: false,
    dirty: false,
    onSave: vi.fn(),
    onClose: vi.fn(),
    onDelete: vi.fn(),
    onMove: vi.fn(),
    onToggleEnabled: vi.fn(),
    onOpenQaTree: vi.fn(),
    ...overrides,
  };

  const view = render(<FileView {...props} />);
  return { ...view, props };
}

function openMoreMenu() {
  fireEvent.click(screen.getByRole("button", { name: "更多" }));
}

/** jsdom 沒有 matchMedia；給了才算有寬度資訊，resize 模擬旋轉手機。 */
function stubViewport(wide: boolean) {
  const listeners = new Set<() => void>();
  const media = {
    matches: wide,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  return {
    resize(nextWide: boolean) {
      media.matches = nextWide;
      act(() => listeners.forEach((listener) => listener()));
    },
  };
}

function isShowingEditor() {
  return screen.queryByRole("textbox", { name: "文件內容" }) !== null;
}

function isShowingPreview() {
  return screen.queryByRole("heading", { name: "門市資訊" }) !== null;
}

describe("FileView", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps unattached QA documents editable from the file view", () => {
    renderFileView({ onRenormalize: vi.fn() });

    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
    expect(screen.getByPlaceholderText("請輸入答案")).toBeTruthy();
    expect(screen.getByRole("button", { name: "儲存" })).toBeTruthy();

    openMoreMenu();
    expect(screen.getByRole("menuitem", { name: "移動…" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "AI 整理排版" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "刪除" })).toBeTruthy();
  });

  it("edits unattached QA documents as structured rows, not raw markdown", () => {
    const { props } = renderFileView({
      editContent: '## Q1\n\nA1\n<!-- qa_metadata: {"img":"","url":""} -->',
    });

    const question = screen.getByPlaceholderText("請輸入問題") as HTMLTextAreaElement;
    expect(question.value).toBe("Q1");

    fireEvent.change(question, { target: { value: "Q1 改" } });
    expect(props.setEditContent).toHaveBeenCalledWith(
      '## Q1 改\n\nA1\n<!-- qa_metadata: {"img":"","url":""} -->',
    );
  });

  it("shows CSV QA content and its image instead of an empty editor", () => {
    renderFileView({
      document: {
        ...baseDocument,
        path: "knowledge/prp.csv",
        extension: ".csv",
        content: "index,q,a,img,url,display\n1,PRP 有哪些生長因子？,答案,PRP(1),,true",
      },
      editContent: "index,q,a,img,url,display\n1,PRP 有哪些生長因子？,答案,PRP(1),,true",
    });

    expect(screen.getByDisplayValue("PRP 有哪些生長因子？")).toBeTruthy();
    const image = screen.getByRole("img", { name: /PRP 有哪些生長因子/ });
    expect(image.getAttribute("src")).toBe(
      "/api/v1/knowledge/qa/images/PRP(1)?project_id=default",
    );
  });

  it("keeps structured QA fields readable when focused in dark mode", () => {
    renderFileView({
      editContent: '## Q1\n\nA1\n<!-- qa_metadata: {"img":"","url":""} -->',
    });

    const question = screen.getByPlaceholderText("請輸入問題");

    // 共用的 .input 底色跟著深淺色走，不再另外設 focus 底色。
    expect(question.className.split(" ")).toContain("input");
    expect(question.className).not.toContain("dark:focus:bg-slate-850");
  });

  it("switches QA documents between the question table and the raw text", () => {
    renderFileView();

    const tableButton = screen.getByRole("button", { name: "問答表" });
    expect(tableButton.getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("button", { name: "編輯" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "原始文字" }));
    const textarea = screen.getByRole("textbox", { name: "問答原始文字" }) as HTMLTextAreaElement;
    expect(textarea.value).toBe(baseDocument.content);
    expect(screen.queryByPlaceholderText("請輸入問題")).toBeNull();

    fireEvent.click(tableButton);
    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
  });

  it("goes back to the question table when another QA document opens", () => {
    const { props, rerender } = renderFileView();

    fireEvent.click(screen.getByRole("button", { name: "原始文字" }));
    rerender(
      <FileView {...props} document={{ ...baseDocument, path: "knowledge/other.md", title: "其他問答" }} />,
    );

    expect(screen.getByRole("button", { name: "問答表" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
  });

  it("keeps attached QA documents editable and only lets them be deleted with their category", () => {
    const { props } = renderFileView({
      document: { ...baseDocument, qa_attached: true },
      onRenormalize: vi.fn(),
    });

    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
    expect(screen.getByRole("button", { name: "儲存" })).toBeTruthy();
    expect(screen.getByText("這份文件屬於快速問答的分類，儲存後分類裡的題目會跟著更新。")).toBeTruthy();

    openMoreMenu();
    expect(screen.queryByRole("menuitem", { name: /移動/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /AI 整理排版/ })).toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: "刪除（連同快速問答的分類）" }));
    expect(props.onDelete).toHaveBeenCalledWith("knowledge/faq.md");

    fireEvent.click(screen.getByRole("button", { name: "前往快速問答" }));
    expect(props.onOpenQaTree).toHaveBeenCalledTimes(1);
  });

  it("only offers quick QA when the document has a category", () => {
    renderFileView({ onOpenQaTree: undefined });

    expect(screen.queryByRole("button", { name: "前往快速問答" })).toBeNull();
  });

  it("gives core documents no way to move or delete them", () => {
    renderFileView({ document: { ...uploadedDocument, is_core: true } });

    expect(screen.queryByRole("button", { name: "更多" })).toBeNull();
    expect(screen.queryByRole("button", { name: "刪除" })).toBeNull();
  });

  it("shows the detected language and lets an admin pin it", () => {
    const onChangeLanguage = vi.fn();
    renderFileView({
      document: { ...baseDocument, source_type: "upload", language: "en", language_source: "auto" },
      onChangeLanguage,
    });

    const trigger = screen.getByRole("combobox", { name: "文件語言" });
    expect(trigger.textContent).toContain("語言");
    expect(trigger.textContent).toContain("自動（English）");
    // 下拉清單是絕對定位，外層一旦可捲動就會把選項裁掉、點不到。
    expect(trigger.closest(".overflow-x-auto")).toBeNull();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "End" });
    fireEvent.keyDown(trigger, { key: "Enter" });

    // End 選到清單最後一個語言（2026-09-30 起是韓文）。
    expect(onChangeLanguage).toHaveBeenCalledWith(expect.objectContaining({ path: "knowledge/faq.md" }), "ko");
  });

  describe("title row", () => {
    it("shows the name with the full file name as its title", () => {
      renderFileView({
        document: {
          ...uploadedDocument,
          path: "knowledge/guides/很長很長的文件名稱_IMG_PRP_1.md",
          title: "很長很長的文件名稱_IMG_PRP_1",
        },
      });

      const heading = screen.getByRole("heading", { name: "很長很長的文件名稱_IMG_PRP_1" });
      expect(heading.getAttribute("title")).toBe("很長很長的文件名稱_IMG_PRP_1.md");
      expect(heading.className).toContain("truncate");
    });

    it.each([
      [{ enabled: true, is_indexed: true, is_indexable: true }, "可被搜尋"],
      [{ enabled: true, is_indexed: false, is_indexable: true }, "處理中"],
      [{ enabled: false, is_indexed: true, is_indexable: true }, "已停用"],
      [{ enabled: true, is_indexed: false, is_indexable: false }, "不會被搜尋"],
    ])("writes out the status %j as %s", (fields, label) => {
      renderFileView({ document: { ...uploadedDocument, ...fields } });

      expect(screen.getByText(label)).toBeTruthy();
    });

    it.each([
      ["upload", "上傳"],
      ["web", "貼網址"],
      ["manual", "自己輸入"],
      ["qa", "問答"],
    ] as const)("labels the %s source as %s", (sourceType, label) => {
      renderFileView({ document: { ...uploadedDocument, source_type: sourceType } });

      expect(screen.getByText(label)).toBeTruthy();
    });

    it("keeps save disabled but readable until something changes", () => {
      renderFileView({ document: uploadedDocument });

      const save = screen.getByRole<HTMLButtonElement>("button", { name: "儲存" });
      expect(save.disabled).toBe(true);
      expect(screen.queryByText("未儲存")).toBeNull();
      // .btn:disabled 的半透明會讓陶土底配白字只剩 1.8:1，這裡要蓋掉。
      expect(save.className).toContain("disabled:opacity-100");
      expect(save.className).toContain("disabled:text-content-muted");
    });

    it("says unsaved and saves once something changed", () => {
      const { props } = renderFileView({ document: uploadedDocument, dirty: true });

      expect(screen.getByText("未儲存")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "儲存" }));
      expect(props.onSave).toHaveBeenCalledTimes(1);
    });

    it("shows saving progress while saving", () => {
      renderFileView({ document: uploadedDocument, dirty: true, saving: true });

      expect(screen.getByRole<HTMLButtonElement>("button", { name: "儲存中…" }).disabled).toBe(true);
    });

    it("hides the back arrow from md up and goes back straight away when nothing changed", () => {
      const { props } = renderFileView({ document: uploadedDocument });

      const back = screen.getByRole("button", { name: "返回" });
      expect(back.className).toContain("md:hidden");

      fireEvent.click(back);
      expect(props.onClose).toHaveBeenCalledTimes(1);
    });

    it("asks before the back arrow throws away unsaved edits", () => {
      const { props } = renderFileView({ document: uploadedDocument, dirty: true });

      fireEvent.click(screen.getByRole("button", { name: "返回" }));
      expect(props.onClose).not.toHaveBeenCalled();
      expect(screen.getByText("離開這份文件後，還沒儲存的修改會消失。")).toBeTruthy();

      fireEvent.click(screen.getByRole("button", { name: "取消" }));
      expect(props.onClose).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "返回" }));
      fireEvent.click(screen.getByRole("button", { name: "不儲存，離開" }));
      expect(props.onClose).toHaveBeenCalledTimes(1);
    });

    it("asks before quick QA throws away unsaved edits", () => {
      const { props } = renderFileView({ dirty: true });

      fireEvent.click(screen.getByRole("button", { name: "前往快速問答" }));
      expect(props.onOpenQaTree).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "不儲存，離開" }));
      expect(props.onOpenQaTree).toHaveBeenCalledTimes(1);
    });
  });

  describe("controls", () => {
    it("only reaches delete through the more menu", () => {
      const { props } = renderFileView({ document: uploadedDocument, onRenormalize: vi.fn() });

      expect(screen.queryByRole("button", { name: /刪除/ })).toBeNull();
      expect(screen.queryByTitle(/刪除/)).toBeNull();
      expect(screen.queryByRole("menuitem", { name: "刪除" })).toBeNull();

      openMoreMenu();
      const deleteItem = screen.getByRole("menuitem", { name: "刪除" });
      expect(deleteItem.className).toContain("text-danger");

      fireEvent.click(deleteItem);
      expect(props.onDelete).toHaveBeenCalledWith("knowledge/faq.md");
    });

    it("keeps move and AI cleanup in the more menu too", () => {
      const onRenormalize = vi.fn();
      const { props } = renderFileView({ document: uploadedDocument, onRenormalize });

      expect(screen.queryByRole("button", { name: /移動/ })).toBeNull();
      expect(screen.queryByRole("button", { name: /AI 整理排版|重新整理/ })).toBeNull();

      openMoreMenu();
      fireEvent.click(screen.getByRole("menuitem", { name: "移動…" }));
      expect(props.onMove).toHaveBeenCalledWith("knowledge/faq.md");

      openMoreMenu();
      fireEvent.click(screen.getByRole("menuitem", { name: "AI 整理排版" }));
      expect(onRenormalize).toHaveBeenCalledWith("knowledge/faq.md");
    });

    it("blocks move and AI cleanup while there are unsaved edits, and says why", () => {
      const onRenormalize = vi.fn();
      const { props } = renderFileView({ document: uploadedDocument, onRenormalize, dirty: true });

      openMoreMenu();
      const move = screen.getByRole("menuitem", { name: /移動…/ });
      const cleanup = screen.getByRole("menuitem", { name: /AI 整理排版/ });
      expect(move.textContent).toContain("請先儲存目前的修改");
      expect(cleanup.textContent).toContain("請先儲存目前的修改");

      fireEvent.click(move);
      fireEvent.click(cleanup);
      expect(props.onMove).not.toHaveBeenCalled();
      expect(onRenormalize).not.toHaveBeenCalled();
    });

    it("shows AI cleanup progress outside the closed menu and blocks a second run", () => {
      const onRenormalize = vi.fn();
      renderFileView({ document: uploadedDocument, onRenormalize, renormalizing: true });

      expect(screen.getByRole("status").textContent).toContain("AI 整理中…");

      openMoreMenu();
      fireEvent.click(screen.getByRole("menuitem", { name: /AI 整理排版/ }));
      expect(onRenormalize).not.toHaveBeenCalled();
    });

    it("writes what the switch does next to it", () => {
      const { props } = renderFileView({ document: uploadedDocument });

      const toggle = screen.getByRole("switch", { name: "AI 會參考這份文件" });
      expect(toggle.getAttribute("aria-checked")).toBe("true");
      expect(toggle.textContent).toBe("AI 會參考這份文件");

      fireEvent.click(toggle);
      expect(props.onToggleEnabled).toHaveBeenCalledWith(uploadedDocument);
    });

    it("says the AI will not use a disabled document", () => {
      renderFileView({ document: { ...uploadedDocument, enabled: false } });

      const toggle = screen.getByRole("switch", { name: "已停用，AI 不會參考" });
      expect(toggle.getAttribute("aria-checked")).toBe("false");
      expect(toggle.textContent).toBe("已停用，AI 不會參考");
    });

    it("does not claim the AI uses a document that can never be searched", () => {
      renderFileView({ document: { ...uploadedDocument, is_indexable: false, is_indexed: false } });

      expect(screen.queryByRole("switch")).toBeNull();
      expect(screen.getByText("不會被搜尋")).toBeTruthy();
    });
  });

  describe("view switch", () => {
    it("shows edit and preview side by side by default on a wide screen", () => {
      renderFileView({ document: uploadedDocument });

      expect(screen.getByRole("button", { name: "並排" }).getAttribute("aria-pressed")).toBe("true");
      expect(isShowingEditor()).toBe(true);
      expect(isShowingPreview()).toBe(true);
      expect(screen.getByText("編輯", { selector: "div" })).toBeTruthy();
      expect(screen.getByText("預覽", { selector: "div" })).toBeTruthy();
    });

    it("wraps long URLs in the preview instead of scrolling it sideways", () => {
      renderFileView({ document: uploadedDocument });

      const preview = screen.getByRole("heading", { name: "門市資訊" }).closest(".prose-container");
      expect(preview?.className).toContain("break-words");
    });

    it("shows one pane at a time when edit or preview is picked", () => {
      renderFileView({ document: uploadedDocument });

      fireEvent.click(screen.getByRole("button", { name: "編輯" }));
      expect(isShowingEditor()).toBe(true);
      expect(isShowingPreview()).toBe(false);

      fireEvent.click(screen.getByRole("button", { name: "預覽" }));
      expect(isShowingEditor()).toBe(false);
      expect(isShowingPreview()).toBe(true);
    });

    it("remembers the pick the next time a document opens", () => {
      const { unmount } = renderFileView({ document: uploadedDocument });
      fireEvent.click(screen.getByRole("button", { name: "預覽" }));
      unmount();

      renderFileView({ document: uploadedDocument });

      expect(screen.getByRole("button", { name: "預覽" }).getAttribute("aria-pressed")).toBe("true");
      expect(isShowingEditor()).toBe(false);
      expect(isShowingPreview()).toBe(true);
    });

    it("offers no side-by-side on a phone and shows one pane at a time", () => {
      stubViewport(false);
      renderFileView({ document: uploadedDocument });

      expect(screen.queryByRole("button", { name: "並排" })).toBeNull();
      expect(screen.getByRole("button", { name: "預覽" }).getAttribute("aria-pressed")).toBe("true");
      expect(isShowingEditor()).toBe(false);
      expect(isShowingPreview()).toBe(true);

      fireEvent.click(screen.getByRole("button", { name: "編輯" }));
      expect(isShowingEditor()).toBe(true);
      expect(isShowingPreview()).toBe(false);
    });

    it("treats a remembered side-by-side as preview on a phone and restores it when wide again", () => {
      const viewport = stubViewport(true);
      renderFileView({ document: uploadedDocument });
      fireEvent.click(screen.getByRole("button", { name: "編輯" }));
      fireEvent.click(screen.getByRole("button", { name: "並排" }));

      viewport.resize(false);
      expect(screen.queryByRole("button", { name: "並排" })).toBeNull();
      expect(isShowingEditor()).toBe(false);
      expect(isShowingPreview()).toBe(true);

      viewport.resize(true);
      expect(screen.getByRole("button", { name: "並排" }).getAttribute("aria-pressed")).toBe("true");
      expect(isShowingEditor()).toBe(true);
      expect(isShowingPreview()).toBe(true);
    });

    it("lets the document be edited from the editor pane", () => {
      const { props } = renderFileView({ document: uploadedDocument });

      fireEvent.change(screen.getByRole("textbox", { name: "文件內容" }), { target: { value: "新內容" } });

      expect(props.setEditContent).toHaveBeenCalledWith("新內容");
    });
  });

  it("no longer takes up room with a banner about uploads", () => {
    const { container } = renderFileView({ document: uploadedDocument });

    expect(container.textContent).not.toContain("由上傳檔案轉換");
    expect(container.textContent).not.toContain("raw/");
  });

  it("truncates a long path in the footer instead of scrolling the row sideways", () => {
    const { container } = renderFileView({
      document: {
        ...uploadedDocument,
        path: "knowledge/guides/2026/很長的資料夾名稱/門市資訊.md",
        source_url: "https://example.com/very/long/source/page",
      },
    });

    const path = screen.getByText("guides/2026/很長的資料夾名稱/門市資訊.md");
    expect(path.getAttribute("title")).toBe("guides/2026/很長的資料夾名稱/門市資訊.md");
    expect(path.className).toContain("truncate");
    expect(path.className).toContain("min-w-0");

    const url = screen.getByText("https://example.com/very/long/source/page");
    expect(url.getAttribute("title")).toBe("https://example.com/very/long/source/page");
    expect(url.className).toContain("truncate");

    expect(path.parentElement?.className).not.toContain("overflow-x-auto");
    expect(container.textContent).not.toContain("knowledge/");
  });

  it("uses nothing smaller than 0.75rem and no raw palette colours", () => {
    const { container } = renderFileView({
      document: { ...uploadedDocument, source_url: "https://example.com" },
      dirty: true,
    });

    const classNames = Array.from(container.querySelectorAll("[class]"))
      .map((element) => element.getAttribute("class"))
      .join(" ");
    expect(classNames).not.toMatch(/text-\[0\.(5|6)\d*rem\]/);
    expect(classNames).not.toMatch(/\b(?:sky|emerald|amber|red|fuchsia)-\d{2,3}\b/);
  });
});
