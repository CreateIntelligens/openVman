import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { KnowledgeNoteFormat } from "../../api";
import { NavigationGuardProvider, useNavigationGuard } from "../../context/NavigationGuardContext";
import NoteComposer from "./NoteComposer";

function GuardProbe() {
  const { hasUnsavedChanges } = useNavigationGuard();
  return <output data-testid="has-unsaved">{String(hasUnsavedChanges)}</output>;
}

function renderComposer(overrides: { creating?: boolean; initialFormat?: KnowledgeNoteFormat } = {}) {
  const props = {
    creating: false,
    onClose: vi.fn(),
    onCreate: vi.fn(),
    ...overrides,
  };
  const view = render(
    <>
      <GuardProbe />
      <NoteComposer {...props} />
    </>,
    { wrapper: NavigationGuardProvider },
  );
  const rerenderComposer = (next: typeof props) => view.rerender(
    <>
      <GuardProbe />
      <NoteComposer {...next} />
    </>,
  );
  return { ...view, props, rerenderComposer };
}

function hasUnsavedChanges(): boolean {
  return screen.getByTestId("has-unsaved").textContent === "true";
}

describe("NoteComposer", () => {
  it("disables create until title and content are filled", () => {
    renderComposer();
    const createButton = screen.getByRole<HTMLButtonElement>("button", { name: "建立文件" });
    expect(createButton.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("標題"), {
      target: { value: "我的筆記" },
    });
    expect(createButton.disabled).toBe(true);

    fireEvent.change(screen.getByRole("textbox", { name: "文件內容" }), {
      target: { value: "一些內容" },
    });
    expect(createButton.disabled).toBe(false);
  });

  it("creates a plain-text note", () => {
    const { props } = renderComposer();
    fireEvent.change(screen.getByLabelText("標題"), {
      target: { value: "我的筆記" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "文件內容" }), {
      target: { value: "一些內容" },
    });
    fireEvent.click(screen.getByRole("button", { name: "建立文件" }));

    expect(props.onCreate).toHaveBeenCalledWith("我的筆記", "一些內容", "text");
  });

  it("creates a qa-format note from the row editor", () => {
    const { props } = renderComposer();

    fireEvent.click(screen.getByRole("button", { name: "問答" }));
    fireEvent.change(screen.getByLabelText("標題"), {
      target: { value: "門市問答" },
    });
    fireEvent.change(screen.getByPlaceholderText("請輸入問題"), {
      target: { value: "營業時間？" },
    });
    fireEvent.change(screen.getByPlaceholderText("請輸入答案"), {
      target: { value: "週一至週五" },
    });

    fireEvent.click(screen.getByRole("button", { name: "建立問答" }));

    expect(props.onCreate).toHaveBeenCalledTimes(1);
    const [title, content, format] = props.onCreate.mock.calls[0];
    expect(title).toBe("門市問答");
    expect(format).toBe("qa");
    expect(content).toContain("## 營業時間？");
    expect(content).toContain("qa_metadata");
  });


  it("keeps create disabled in qa mode until a row has a question", () => {
    renderComposer();
    fireEvent.click(screen.getByRole("button", { name: "問答" }));
    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("標題"), {
      target: { value: "門市問答" },
    });
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "建立問答" }).disabled).toBe(true);
  });

  it("closes from the back button", () => {
    const { props } = renderComposer();
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    expect(props.onClose).toHaveBeenCalled();
  });

  it("starts on plain text unless told otherwise", () => {
    renderComposer();

    expect(screen.getByRole("heading", { name: "自己輸入文件" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "純文字" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("textbox", { name: "文件內容" })).toBeTruthy();
  });

  it("can open straight on typing in questions", () => {
    renderComposer({ initialFormat: "qa" });

    expect(screen.getByRole("heading", { name: "自己輸入問答" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "問答" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "文件內容" })).toBeNull();
  });

  it("follows a new initial format while open and keeps what was typed", () => {
    const { props, rerenderComposer } = renderComposer();
    fireEvent.change(screen.getByRole("textbox", { name: "文件內容" }), {
      target: { value: "打到一半的內容" },
    });

    rerenderComposer({ ...props, initialFormat: "qa" });
    expect(screen.getByPlaceholderText("請輸入問題")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "純文字" }));
    expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "文件內容" }).value).toBe("打到一半的內容");
  });

  it("does not undo the format the user picked when re-rendered", () => {
    const { props, rerenderComposer } = renderComposer({ initialFormat: "qa" });

    fireEvent.click(screen.getByRole("button", { name: "純文字" }));
    rerenderComposer({ ...props, initialFormat: "qa", creating: true });

    expect(screen.getByRole("button", { name: "純文字" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("counts as unsaved only once something is typed", () => {
    renderComposer();
    expect(hasUnsavedChanges()).toBe(false);

    fireEvent.change(screen.getByLabelText("標題"), { target: { value: "新的筆記" } });
    expect(hasUnsavedChanges()).toBe(true);

    fireEvent.change(screen.getByLabelText("標題"), { target: { value: "  " } });
    expect(hasUnsavedChanges()).toBe(false);
  });

  it("counts typed questions as unsaved, also after switching to the other format", () => {
    renderComposer({ initialFormat: "qa" });
    expect(hasUnsavedChanges()).toBe(false);

    fireEvent.change(screen.getByPlaceholderText("請輸入問題"), { target: { value: "幾點開門？" } });
    fireEvent.change(screen.getByPlaceholderText("請輸入答案"), { target: { value: "九點" } });
    expect(hasUnsavedChanges()).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "純文字" }));
    expect(hasUnsavedChanges()).toBe(true);
  });

  it("explains the result in plain words, without internal terms or paths", () => {
    const { container } = renderComposer();
    expect(screen.getByText("建立後會放在「文件」的 notes 資料夾，AI 回答時會參考。")).toBeTruthy();
    expect(container.textContent).toContain("0 字");
    expect(container.textContent).not.toMatch(/knowledge\/|chars|手動|來源/);

    fireEvent.click(screen.getByRole("button", { name: "問答" }));
    expect(screen.getByText("一題一列。建立後會放進快速問答，分類名稱就是上面的標題。")).toBeTruthy();
    expect(container.textContent).not.toMatch(/節點|問答樹|knowledge\/|QA/);
  });

  it("shows progress while creating", () => {
    renderComposer({ creating: true });

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "建立中…" }).disabled).toBe(true);
  });
});
