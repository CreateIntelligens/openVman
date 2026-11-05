import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SourcePanel from "./SourcePanel";

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
    skipNormalize: false,
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
  it("writes the rules on the screen instead of hiding them in a tooltip", () => {
    renderPanel();

    expect(screen.getByRole("button", { name: "把檔案拖到這裡，或點這裡選擇檔案" })).toBeTruthy();
    expect(screen.getByText("有「問題」「答案」欄位的 Excel 或 CSV，會放進快速問答。")).toBeTruthy();
    expect(screen.getByText("其他文件由 AI 整理排版後加入知識庫，內容維持原本的語言，不會翻譯。")).toBeTruthy();
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

  it("toggles skipping the AI step", () => {
    const { onSkipNormalizeChange } = renderPanel();

    fireEvent.click(screen.getByRole("checkbox", { name: "這批已經整理好了，不要讓 AI 修改內容" }));

    expect(onSkipNormalizeChange).toHaveBeenCalledWith(true);
  });

  it("shows the checkbox as it is", () => {
    renderPanel({ skipNormalize: true });

    const checkbox = screen.getByRole("checkbox", { name: "這批已經整理好了，不要讓 AI 修改內容" }) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
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
});
