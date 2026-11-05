import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import QaDocEditor from "../QaDocEditor";
import { moveToInsertion } from "./rowReorder";

const CSV = "index,q,a,img,url,display\n3,甲題,甲答,,,true\n7,乙題,乙答,,,true\n9,丙題,丙答,,,true";

function dragQuestion(from: string, to: string, clientY: number) {
  const dataTransfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
  const article = (label: string) => screen.getByDisplayValue(label).closest("article") as HTMLElement;
  const at = (event: Event) => {
    Object.defineProperty(event, "clientY", { value: clientY });
    return event;
  };
  fireEvent.dragStart(article(from).querySelector("[draggable]") as HTMLElement, { dataTransfer });
  fireEvent(article(to), at(createEvent.dragOver(article(to), { dataTransfer })));
  fireEvent(article(to), at(createEvent.drop(article(to), { dataTransfer })));
}

describe("moveToInsertion", () => {
  it("moves a row to the insertion point", () => {
    expect(moveToInsertion(["a", "b", "c"], 0, 3)).toEqual(["b", "c", "a"]);
    expect(moveToInsertion(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moveToInsertion(["a", "b", "c"], 0, 2)).toEqual(["b", "a", "c"]);
  });
});

describe("compact QA rows", () => {
  it("sizes fields to their content instead of a fixed tall box", () => {
    render(<QaDocEditor content={"## 短問題\n\n短答案\n"} onChange={vi.fn()} />);

    expect(screen.getByPlaceholderText("請輸入問題").getAttribute("rows")).toBe("1");
    expect(screen.getByPlaceholderText("請輸入答案").getAttribute("rows")).toBe("1");
  });

  it("keeps empty image and link fields out of the way until asked for", () => {
    render(<QaDocEditor content={"## 問\n\n答\n"} onChange={vi.fn()} />);

    expect(screen.queryByPlaceholderText("圖片 ID")).toBeNull();
    expect(screen.queryByPlaceholderText("外部連結")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "連結" }));

    expect(screen.getByPlaceholderText("圖片 ID")).toBeTruthy();
    expect(screen.getByPlaceholderText("外部連結")).toBeTruthy();
  });

  it("shows image and link fields straight away when they have a value", () => {
    render(
      <QaDocEditor
        content={'## 問\n\n答\n<!-- qa_metadata: {"img": "a.png", "url": "https://x.test"} -->'}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByPlaceholderText("圖片 ID")).toHaveProperty("value", "a.png");
    expect(screen.getByPlaceholderText("外部連結")).toHaveProperty("value", "https://x.test");
  });

  it("only the handle can start a drag, so text in the fields stays selectable", () => {
    render(<QaDocEditor content={"## 問\n\n答\n"} onChange={vi.fn()} />);

    const row = screen.getByDisplayValue("問").closest("article") as HTMLElement;
    expect(row.getAttribute("draggable")).toBeNull();
    expect(row.querySelectorAll("[draggable]").length).toBe(1);
  });

  it("dragging writes the new order, reusing the CSV's own index values", () => {
    const onChange = vi.fn();
    render(<QaDocEditor content={CSV} format="csv" onChange={onChange} />);

    dragQuestion("丙題", "甲題", -1);

    const written = String(onChange.mock.lastCall?.[0]).split("\n").slice(1);
    expect(written.map((line) => line.split(",").slice(0, 2).join(","))).toEqual([
      "3,丙題",
      "7,甲題",
      "9,乙題",
    ]);
  });
});
