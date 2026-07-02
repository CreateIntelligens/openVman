import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NormalizationPreviewModal from "./NormalizationPreviewModal";

describe("NormalizationPreviewModal", () => {
  function renderNormalizationPreviewModal() {
    const props = {
      path: "knowledge/source.md",
      content: "# 標題\n\n內容",
      applying: false,
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
});
