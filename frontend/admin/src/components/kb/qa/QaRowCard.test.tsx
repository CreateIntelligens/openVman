import { act, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import QaDocEditor from "../QaDocEditor";
import { moveToInsertion } from "./rowReorder";

const qaNodeMocks = vi.hoisted(() => ({ uploadImage: vi.fn() }));

vi.mock("../../../hooks/useQaNodes", () => ({
  useQaNodes: () => qaNodeMocks,
}));

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

function pickFile(container: HTMLElement) {
  fireEvent.change(container.querySelector('input[type="file"]') as HTMLInputElement, {
    target: { files: [new File(["fake"], "qa.png", { type: "image/png" })] },
  });
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

    expect(screen.queryByPlaceholderText("圖片編號")).toBeNull();
    expect(screen.queryByPlaceholderText("https://")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "第 1 題加圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "第 1 題加連結" }));

    expect(screen.getByPlaceholderText("圖片編號")).toBeTruthy();
    expect(screen.getByPlaceholderText("https://")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "第 1 題加圖片" })).toBeNull();
  });

  it("shows image and link fields straight away when they have a value", () => {
    render(
      <QaDocEditor
        content={'## 問\n\n答\n<!-- qa_metadata: {"img": "a.png", "url": "https://x.test"} -->'}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByPlaceholderText("圖片編號")).toHaveProperty("value", "a.png");
    expect(screen.getByPlaceholderText("https://")).toHaveProperty("value", "https://x.test");
  });

  it("labels the extra fields on screen, in plain words", () => {
    render(
      <QaDocEditor
        content={'## 問\n\n答\n<!-- qa_metadata: {"img": "a.png", "url": "https://x.test"} -->'}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("圖片編號（AI 用這題回答時會附上這張圖）")).toBeTruthy();
    expect(screen.getByText("相關連結網址（AI 用這題回答時會附上「開啟相關連結」）")).toBeTruthy();
    expect(screen.queryByText(/圖片 ID/)).toBeNull();
  });

  // 實測：刪掉舊編號準備重打時，欄位當場消失。
  it("keeps the image field open while its number is being retyped", () => {
    render(
      <QaDocEditor
        content={'## 問\n\n答\n<!-- qa_metadata: {"img": "a.png", "url": ""} -->'}
        onChange={vi.fn()}
      />,
    );

    const field = screen.getByPlaceholderText("圖片編號");
    // 第一次改動前欄位是因為有值才顯示的，要先確認它在清空後還留著。
    fireEvent.change(field, { target: { value: "" } });

    expect(screen.queryByPlaceholderText("圖片編號")).not.toBeNull();
  });

  it("can take the image and the link off again", () => {
    const onChange = vi.fn();
    render(
      <QaDocEditor
        content={'## 問\n\n答\n<!-- qa_metadata: {"img": "a.png", "url": "https://x.test"} -->'}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "第 1 題移除圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "第 1 題移除連結" }));

    expect(screen.queryByPlaceholderText("圖片編號")).toBeNull();
    expect(screen.queryByPlaceholderText("https://")).toBeNull();
    expect(onChange.mock.lastCall?.[0]).toContain('"img":""');
    expect(onChange.mock.lastCall?.[0]).toContain('"url":""');
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

  it("gives every row a clear number and a delete button with a word on it", () => {
    render(<QaDocEditor content={"## 問一\n\n答一\n\n## 問二\n\n答二\n"} onChange={vi.fn()} />);

    const second = screen.getByDisplayValue("問二").closest("article") as HTMLElement;
    expect(within(second).getByText("第 2 題")).toBeTruthy();
    expect(within(second).getByRole("button", { name: "刪除第 2 題" }).textContent).toBe("刪除");
  });

  it("says shown or hidden in words, and explains what hiding does", () => {
    const onChange = vi.fn();
    render(<QaDocEditor content={"## 問\n\n答\n"} onChange={onChange} />);

    expect(screen.getByText(/「已隱藏」的問題不會出現在訪客的選單，但 AI 回答時還是會用/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "第 1 題顯示中，按一下隱藏" }).textContent).toContain("顯示中");

    fireEvent.click(screen.getByRole("button", { name: "第 1 題顯示中，按一下隱藏" }));

    expect(screen.getByRole("button", { name: "第 1 題已隱藏，按一下改成顯示" }).textContent).toContain("已隱藏");
    expect(onChange.mock.lastCall?.[0]).toContain('"hidden":true');
  });

  it("keeps a row's open fields with that row when another row is deleted", () => {
    render(<QaDocEditor content={"## 問一\n\n答一\n\n## 問二\n\n答二\n"} onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "第 1 題加圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));

    expect(screen.queryByPlaceholderText("圖片編號")).toBeNull();
  });
});

describe("QaDocEditor", () => {
  const originalScrollIntoView = Element.prototype.scrollIntoView;
  let scrolledTo: Element[] = [];

  beforeEach(() => {
    vi.clearAllMocks();
    scrolledTo = [];
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
      scrolledTo.push(this);
    };
    qaNodeMocks.uploadImage.mockResolvedValue({ image_id: "img_123" });
  });

  afterEach(() => {
    Element.prototype.scrollIntoView = originalScrollIntoView;
  });

  it("adds a question from above the list, then goes to it", async () => {
    render(<QaDocEditor content={"## 問\n\n答\n"} onChange={vi.fn()} />);

    const add = screen.getByRole("button", { name: "新增問題" });
    expect(screen.queryByRole("button", { name: /新增一列/ })).toBeNull();
    const firstRow = screen.getAllByRole("article")[0];
    expect(add.compareDocumentPosition(firstRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(add);

    const rows = screen.getAllByRole("article");
    expect(rows).toHaveLength(2);
    await waitFor(() => expect(scrolledTo).toContain(rows[1]));
    expect(document.activeElement).toBe(within(rows[1]).getByPlaceholderText("請輸入問題"));
  });

  it("says what to do when every question was deleted", () => {
    render(<QaDocEditor content={"## 問\n\n答\n"} onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));

    expect(screen.getByText("這份文件還沒有問題")).toBeTruthy();
    expect(screen.getByText("按上面的「新增問題」開始輸入。")).toBeTruthy();
  });

  it("uploads an image into the markdown document", async () => {
    const onChange = vi.fn();
    const { container } = render(<QaDocEditor content={"## 問\n\n答\n"} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "第 1 題加圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "第 1 題上傳圖片" }));
    pickFile(container);

    await waitFor(() => expect(screen.getByPlaceholderText("圖片編號")).toHaveProperty("value", "img_123"));
    expect(qaNodeMocks.uploadImage).toHaveBeenCalledTimes(1);
    expect(onChange.mock.lastCall?.[0]).toContain('"img":"img_123"');
    expect(screen.getByText("圖片已上傳，編號已經填好。")).toBeTruthy();
  });

  it("uploads an image into the CSV document, keeping its other columns", async () => {
    const onChange = vi.fn();
    const { container } = render(<QaDocEditor content={CSV} format="csv" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "第 2 題加圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "第 2 題上傳圖片" }));
    pickFile(container);

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const written = String(onChange.mock.lastCall?.[0]).split("\n");
    expect(written[2]).toBe("7,乙題,乙答,img_123,,true");
  });

  it("does not lose what was typed while the image was uploading", async () => {
    let finish!: (value: { image_id: string }) => void;
    qaNodeMocks.uploadImage.mockReturnValueOnce(new Promise((resolve) => {
      finish = resolve;
    }));
    const onChange = vi.fn();
    const { container } = render(<QaDocEditor content={"## 問一\n\n答一\n\n## 問二\n\n答二\n"} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "第 2 題加圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "第 2 題上傳圖片" }));
    pickFile(container);
    fireEvent.change(screen.getByDisplayValue("問一"), { target: { value: "上傳時改的字" } });
    fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));
    fireEvent.click(screen.getByRole("button", { name: "新增問題" }));

    await act(async () => finish({ image_id: "img_123" }));

    const row = screen.getByDisplayValue("問二").closest("article") as HTMLElement;
    expect(within(row).getByPlaceholderText("圖片編號")).toHaveProperty("value", "img_123");
    expect(String(onChange.mock.lastCall?.[0])).toContain("## 問二");
    expect(String(onChange.mock.lastCall?.[0])).toContain('"img":"img_123"');
  });

  it("drops the result quietly when the row is gone by the time the upload ends", async () => {
    let finish!: (value: { image_id: string }) => void;
    qaNodeMocks.uploadImage.mockReturnValueOnce(new Promise((resolve) => {
      finish = resolve;
    }));
    const onChange = vi.fn();
    const { container } = render(<QaDocEditor content={"## 問一\n\n答一\n\n## 問二\n\n答二\n"} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "第 2 題加圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "第 2 題上傳圖片" }));
    pickFile(container);
    fireEvent.click(screen.getByRole("button", { name: "刪除第 2 題" }));
    const callsBefore = onChange.mock.calls.length;

    await act(async () => finish({ image_id: "img_123" }));

    expect(onChange.mock.calls.length).toBe(callsBefore);
    expect(screen.queryByText("圖片已上傳，編號已經填好。")).toBeNull();
  });

  it("shows a failed upload on screen and leaves the document alone", async () => {
    qaNodeMocks.uploadImage.mockRejectedValueOnce(new Error("不支援的圖片格式"));
    const onChange = vi.fn();
    const { container } = render(<QaDocEditor content={"## 問\n\n答\n"} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "第 1 題加圖片" }));
    fireEvent.click(screen.getByRole("button", { name: "第 1 題上傳圖片" }));
    pickFile(container);

    expect((await screen.findByRole("alert")).textContent).toBe("不支援的圖片格式");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("re-reads the rows when another document is opened", () => {
    const { rerender } = render(<QaDocEditor content={"## 舊問題\n\n舊答案\n"} onChange={vi.fn()} />);

    rerender(<QaDocEditor content={"## 新問題\n\n新答案\n"} onChange={vi.fn()} />);

    expect(screen.getByDisplayValue("新問題")).toBeTruthy();
    expect(screen.queryByDisplayValue("舊問題")).toBeNull();
  });
});
