import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NoteModal from "./NoteModal";

describe("NoteModal", () => {
  function renderNoteModal() {
    const props = {
      noteTitle: "筆記",
      setNoteTitle: vi.fn(),
      noteContent: "內容",
      setNoteContent: vi.fn(),
      creating: false,
      onClose: vi.fn(),
      onCreate: vi.fn(),
    };
    const view = render(<NoteModal {...props} />);
    return { ...view, props };
  }

  it("closes from Escape and outside pointer release", () => {
    const { container, props } = renderNoteModal();
    const overlay = container.firstElementChild as HTMLElement;

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.pointerDown(overlay);
    fireEvent.pointerUp(overlay);

    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("does not close when pointer starts inside the modal and releases outside", () => {
    const { container, props } = renderNoteModal();
    const overlay = container.firstElementChild as HTMLElement;
    const modalContent = screen.getByText("新增手動來源").closest("div") as HTMLElement;

    fireEvent.pointerDown(modalContent);
    fireEvent.pointerUp(overlay);

    expect(props.onClose).not.toHaveBeenCalled();
  });
});
