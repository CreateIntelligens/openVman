import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { existsSync } from "node:fs";
import { resolve } from "node:path";

import SourcePanel, { IMPORT_TEMPLATES } from "./SourcePanel";

function renderPanel(overrides: Partial<Parameters<typeof SourcePanel>[0]> = {}) {
  const props = {
    onPickFiles: vi.fn(),
    maxUploadLabel: "100 MB",
    targetDir: "knowledge",
    targetOptions: [
      { value: "knowledge", label: "文件（最上層）" },
      { value: "knowledge/gear", label: "gear" },
    ],
    onTargetDirChange: vi.fn(),
    skipNormalize: true,
    onSkipNormalizeChange: vi.fn(),
    crawlUrlValue: "",
    setCrawlUrlValue: vi.fn(),
    crawling: false,
    onCrawl: vi.fn(),
    onOpenComposer: vi.fn(),
    ...overrides,
  };
  render(<SourcePanel {...props} />);
  return props;
}

describe("SourcePanel", () => {
  it("hides the AI cleanup choice from accounts without the permission", () => {
    renderPanel({ allowAiCleanup: false });

    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByText(/先讓 AI 整理排版/)).toBeNull();
    expect(screen.queryByText(/每次上傳開始後/)).toBeNull();
    expect(screen.getByText(/這批文件會直接放進知識庫/)).toBeTruthy();
  });

  it("offers both choices to accounts with the permission", () => {
    renderPanel();

    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByText(/先讓 AI 整理排版/)).toBeTruthy();
  });

  it("writes the rules on the screen instead of hiding them in a tooltip", () => {
    renderPanel();

    expect(screen.getByRole("button", { name: "把檔案拖到這裡，或點這裡選擇檔案" })).toBeTruthy();
    expect(screen.getByText("有「問題」「答案」欄位的 Excel 或 CSV，會放進快速問答。")).toBeTruthy();
    expect(screen.getByText(/中文、英文、西文混在同一張表也可以/)).toBeTruthy();
    expect(screen.getByText("其他文件會切成段落加入知識庫，AI 回答時查得到，不會變成問答。選 AI 整理時，內容維持原本的語言，不會翻譯。")).toBeTruthy();
    expect(screen.getByText(/每個檔案 100 MB 以內/)).toBeTruthy();
    expect(screen.getByText(/Excel（\.xlsx）/)).toBeTruthy();
    expect(screen.queryByText(/暫存區|採納|raw/)).toBeNull();
  });

  it("only accepts the formats that can really be imported", () => {
    renderPanel();

    const input = screen.getByTestId("knowledge-upload-input") as HTMLInputElement;
    expect(input.accept).toBe(".xlsx,.csv,.docx,.pdf,.md,.txt");
    expect(input.accept).not.toContain("pptx");
    expect(input.multiple).toBe(true);
  });

  it("opens the file picker from the big button", () => {
    renderPanel();
    const input = screen.getByTestId("knowledge-upload-input") as HTMLInputElement;
    const click = vi.spyOn(input, "click");

    fireEvent.click(screen.getByRole("button", { name: "把檔案拖到這裡，或點這裡選擇檔案" }));

    expect(click).toHaveBeenCalledTimes(1);
  });

  it("hands over the picked files and lets the same file be picked again", () => {
    const { onPickFiles } = renderPanel();
    const input = screen.getByTestId("knowledge-upload-input") as HTMLInputElement;
    const picked = new File(["x"], "a.md");

    fireEvent.change(input, { target: { files: [picked] } });

    expect(onPickFiles).toHaveBeenCalledWith([picked]);
    expect(input.value).toBe("");
  });

  const DIRECT = "直接放進知識庫（內容不變，系統自動切段，AI 回答時查得到）";
  const TIDY = "先讓 AI 整理排版再放進去（適合掃描錯字多、排版很亂的檔案）";

  // 實測：勾選框在拖放區下面，選了檔案就開始上傳，由上往下操作的人來不及勾。
  it("asks how to bring the batch in above the drop zone, before any file is picked", () => {
    renderPanel();

    const direct = screen.getByRole("radio", { name: DIRECT });
    const tidy = screen.getByRole("radio", { name: TIDY });
    const dropZone = screen.getByRole("button", { name: "把檔案拖到這裡，或點這裡選擇檔案" });
    expect(direct.compareDocumentPosition(tidy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(tidy.compareDocumentPosition(dropZone) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("puts files in directly by default, and switches to letting the AI tidy up", () => {
    const { onSkipNormalizeChange } = renderPanel();

    expect((screen.getByRole("radio", { name: DIRECT }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: TIDY }) as HTMLInputElement).checked).toBe(false);

    fireEvent.click(screen.getByRole("radio", { name: TIDY }));
    expect(onSkipNormalizeChange).toHaveBeenCalledWith(false);
  });

  it("shows the AI tidy choice once picked, and can go back to putting files in directly", () => {
    const { onSkipNormalizeChange } = renderPanel({ skipNormalize: false });

    expect((screen.getByRole("radio", { name: TIDY }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: DIRECT }) as HTMLInputElement).checked).toBe(false);

    fireEvent.click(screen.getByRole("radio", { name: DIRECT }));
    expect(onSkipNormalizeChange).toHaveBeenCalledWith(true);
  });

  it("says the choice goes back to the default after each upload", () => {
    renderPanel();

    expect(screen.getByText("每次上傳開始後，會回到「直接放進知識庫」。問答表不看這個設定。")).toBeTruthy();
  });

  it("picks the target folder from the real folders", () => {
    const { onTargetDirChange } = renderPanel();

    const select = screen.getByRole("combobox", { name: "放到哪個資料夾" });
    expect(select.textContent).toContain("文件（最上層）");
    fireEvent.click(select);
    fireEvent.mouseDown(screen.getByRole("option", { name: "gear" }));

    expect(onTargetDirChange).toHaveBeenCalledWith("knowledge/gear");
  });

  it("imports a pasted address with the button and with Enter", () => {
    const { onCrawl, setCrawlUrlValue } = renderPanel({ crawlUrlValue: "https://example.com" });

    const input = screen.getByLabelText(/貼網址/);
    fireEvent.change(input, { target: { value: "https://example.com/a" } });
    expect(setCrawlUrlValue).toHaveBeenCalledWith("https://example.com/a");

    fireEvent.click(screen.getByRole("button", { name: "匯入" }));
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCrawl).toHaveBeenCalledTimes(2);
  });

  it("does not offer importing without an address", () => {
    renderPanel();

    expect((screen.getByRole("button", { name: "匯入" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows that an address is being imported", () => {
    const { onCrawl } = renderPanel({ crawlUrlValue: "https://example.com", crawling: true });

    const button = screen.getByRole("button", { name: "匯入中…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.keyDown(screen.getByLabelText(/貼網址/), { key: "Enter" });
    expect(onCrawl).not.toHaveBeenCalled();
  });

  it("opens the composer in the right format", () => {
    const { onOpenComposer } = renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "自己輸入一篇文件" }));
    expect(onOpenComposer).toHaveBeenLastCalledWith("text");
    fireEvent.click(screen.getByRole("button", { name: "自己輸入問答" }));
    expect(onOpenComposer).toHaveBeenLastCalledWith("qa");
  });

  it("offers example files that exist in public/templates", () => {
    renderPanel();

    const links = IMPORT_TEMPLATES.map((template) =>
      screen.getByRole("link", { name: template.label }));
    links.forEach((link, position) => {
      const file = IMPORT_TEMPLATES[position].file;
      expect(link.getAttribute("download")).toBe(file);
      expect(decodeURIComponent(link.getAttribute("href") ?? "")).toBe(`/admin/templates/${file}`);
      expect(existsSync(resolve(__dirname, "../../../public/templates", file))).toBe(true);
    });
  });
});

