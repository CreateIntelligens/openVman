import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NoteComposer from "./NoteComposer";

function renderComposer(creating = false) {
  const props = {
    creating,
    onClose: vi.fn(),
    onCreate: vi.fn(),
  };
  const view = render(<NoteComposer {...props} />);
  return { ...view, props };
}

describe("NoteComposer", () => {
  it("disables create until title and content are filled", () => {
    renderComposer();
    const createButton = screen.getByRole<HTMLButtonElement>("button", { name: /建立來源/ });
    expect(createButton.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/產品定位整理/), {
      target: { value: "我的筆記" },
    });
    expect(createButton.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/貼上整理好的知識內容/), {
      target: { value: "一些內容" },
    });
    expect(createButton.disabled).toBe(false);
  });

  it("creates a plain-text note", () => {
    const { props } = renderComposer();
    fireEvent.change(screen.getByPlaceholderText(/產品定位整理/), {
      target: { value: "我的筆記" },
    });
    fireEvent.change(screen.getByPlaceholderText(/貼上整理好的知識內容/), {
      target: { value: "一些內容" },
    });
    fireEvent.click(screen.getByRole("button", { name: /建立來源/ }));

    expect(props.onCreate).toHaveBeenCalledWith("我的筆記", "一些內容", "text");
  });

  it("creates a qa-format note from the row editor", () => {
    const { props } = renderComposer();

    fireEvent.click(screen.getByRole("button", { name: /QA 問答/ }));
    fireEvent.change(screen.getByPlaceholderText(/產品定位整理/), {
      target: { value: "門市問答" },
    });
    fireEvent.change(screen.getByPlaceholderText("請輸入問題"), {
      target: { value: "營業時間？" },
    });
    fireEvent.change(screen.getByPlaceholderText("請輸入答案"), {
      target: { value: "週一至週五" },
    });

    fireEvent.click(screen.getByRole("button", { name: /建立來源/ }));

    expect(props.onCreate).toHaveBeenCalledTimes(1);
    const [title, content, format] = props.onCreate.mock.calls[0];
    expect(title).toBe("門市問答");
    expect(format).toBe("qa");
    expect(content).toContain("## 營業時間？");
    expect(content).toContain("qa_metadata");
  });


  it("keeps create disabled in qa mode until a row has a question", () => {
    renderComposer();
    fireEvent.click(screen.getByRole("button", { name: /QA 問答/ }));
    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/產品定位整理/), {
      target: { value: "門市問答" },
    });
    expect(screen.getByRole<HTMLButtonElement>("button", { name: /建立來源/ }).disabled).toBe(true);
  });

  it("closes from the back button", () => {
    const { props } = renderComposer();
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    expect(props.onClose).toHaveBeenCalled();
  });
});
