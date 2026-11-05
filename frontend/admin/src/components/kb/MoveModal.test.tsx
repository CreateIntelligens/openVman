import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { KnowledgeDocumentSummary } from "../../api";
import MoveModal from "./MoveModal";

describe("MoveModal", () => {
  function renderMoveModal() {
    const props = {
      sourcePaths: ["knowledge/faq/source.md"],
      allDocuments: [] as KnowledgeDocumentSummary[],
      serverDirs: ["knowledge", "knowledge/faq"],
      onMove: vi.fn(),
      onClose: vi.fn(),
    };
    const view = render(<MoveModal {...props} />);
    return { ...view, props };
  }

  it("closes from Escape and outside pointer release", () => {
    const { container, props } = renderMoveModal();
    const overlay = container.firstElementChild as HTMLElement;

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.pointerDown(overlay);
    fireEvent.pointerUp(overlay);

    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("calls the top level 文件 like the tree does and never shows the internal path", () => {
    const { props } = renderMoveModal();
    const dialog = screen.getByRole("dialog", { name: "移動文件" });

    expect(dialog.textContent).not.toContain("knowledge");
    expect(dialog.textContent).toContain("移到「文件 › faq」");

    fireEvent.click(screen.getByRole("button", { name: "文件（最上層）" }));

    expect(dialog.textContent).not.toContain("knowledge");
    expect(dialog.textContent).toContain("移到「文件」");

    fireEvent.click(screen.getByRole("button", { name: "移動" }));
    expect(props.onMove).toHaveBeenCalledWith("knowledge");
  });

  it("does not offer to move a file to where it already is", () => {
    renderMoveModal();

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "移動" }).disabled).toBe(true);
  });
});
