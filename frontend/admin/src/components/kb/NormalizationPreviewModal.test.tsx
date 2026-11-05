import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NormalizationPreviewModal from "./NormalizationPreviewModal";

describe("NormalizationPreviewModal", () => {
  function renderNormalizationPreviewModal(applying = false) {
    const props = {
      path: "knowledge/guides/source.md",
      content: "# 標題\n\n內容",
      applying,
      onApply: vi.fn(),
      onClose: vi.fn(),
    };
    const view = render(<NormalizationPreviewModal {...props} />);
    return { ...view, props };
  }

  it("closes from Escape and outside pointer release", () => {
    const { container, props } = renderNormalizationPreviewModal();
    const overlay = container.firstElementChild as HTMLElement;

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.pointerDown(overlay);
    fireEvent.pointerUp(overlay);

    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("says what applying does in plain words, without the internal path", () => {
    const { container, props } = renderNormalizationPreviewModal();

    expect(screen.getByRole("heading", { name: "AI 整理排版預覽" })).toBeTruthy();
    expect(screen.getByText("guides/source.md").getAttribute("title")).toBe("guides/source.md");
    expect(screen.getByText("套用後，這份內容會取代原本的文件。原本的內容會先留一份備份。")).toBeTruthy();
    expect(container.textContent).not.toContain("knowledge/");

    fireEvent.click(screen.getByRole("button", { name: "套用這份內容" }));
    expect(props.onApply).toHaveBeenCalledTimes(1);
  });

  it("can be closed with a named button", () => {
    const { props } = renderNormalizationPreviewModal();

    fireEvent.click(screen.getByRole("button", { name: "關閉" }));

    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("blocks both buttons while applying", () => {
    renderNormalizationPreviewModal(true);

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "套用中…" }).disabled).toBe(true);
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "取消" }).disabled).toBe(true);
  });
});
