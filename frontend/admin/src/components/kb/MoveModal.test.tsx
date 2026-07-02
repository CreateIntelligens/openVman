import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { KnowledgeDocumentSummary } from "../../api";
import MoveModal from "./MoveModal";

describe("MoveModal", () => {
  function renderMoveModal() {
    const props = {
      sourcePath: "knowledge/faq/source.md",
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
});
