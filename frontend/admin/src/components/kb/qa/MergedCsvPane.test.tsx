import { act, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NavigationGuardProvider, useNavigationGuard } from "../../../context/NavigationGuardContext";
import type { MergedQaItem } from "../../../hooks/useQaNodes";
import MergedCsvPane from "./MergedCsvPane";

const qaNodeMocks = vi.hoisted(() => ({
  fetchMergedQa: vi.fn(),
  saveMergedQa: vi.fn(),
  uploadImage: vi.fn(),
}));

vi.mock("../../../hooks/useQaNodes", () => ({
  useQaNodes: () => qaNodeMocks,
}));

function makeRow(q: string, overrides: Partial<MergedQaItem> = {}): MergedQaItem {
  return {
    index: "1",
    q,
    a: `${q}的答案`,
    img: "",
    url: "",
    source_file: "knowledge/qa/faq.csv",
    hidden: false,
    ...overrides,
  };
}

function makeRows(count: number): MergedQaItem[] {
  return Array.from({ length: count }, (_, position) =>
    makeRow(`問題${position + 1}`, { index: String(position + 1) }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type PaneProps = ComponentProps<typeof MergedCsvPane>;

function pane(props: Partial<PaneProps> = {}) {
  return (
    <NavigationGuardProvider>
      <MergedCsvPane nodeId="root" nodeLabel="Root" {...props} />
    </NavigationGuardProvider>
  );
}

function renderPane(props: Partial<PaneProps> = {}) {
  const onStatus = vi.fn();
  const onSuccess = vi.fn();
  const paneProps = { onStatus, onSuccess, ...props };
  const utils = render(pane(paneProps));
  return {
    ...utils,
    onStatus,
    onSuccess,
    update: (next: Partial<PaneProps>) => utils.rerender(pane({ ...paneProps, ...next })),
  };
}

// 搜尋框裡可能也是同樣的字，所以只找問答欄位。
const article = (question: string) =>
  screen
    .getAllByDisplayValue(question)
    .find((field) => field.tagName === "TEXTAREA")
    ?.closest("article") as HTMLElement;
const articles = () => screen.getAllByRole("article");
const questionValues = () =>
  screen
    .queryAllByPlaceholderText("請輸入問題")
    .map((field) => (field as HTMLTextAreaElement).value);
const saveButton = () => screen.getByRole("button", { name: /儲存變更|儲存中/ }) as HTMLButtonElement;
const cancelButton = () => screen.getByRole("button", { name: "取消變更" }) as HTMLButtonElement;
const addButton = () => screen.getByRole("button", { name: "新增問題" });
const searchBox = () => screen.getByRole("searchbox", { name: "搜尋這個分類的問題和答案" });
const lastStatus = (onStatus: ReturnType<typeof vi.fn>) => onStatus.mock.lastCall?.[0];
const savedPayload = () =>
  qaNodeMocks.saveMergedQa.mock.lastCall?.[1] as Array<MergedQaItem & { index: string }>;

async function editQuestion(from: string, to: string) {
  fireEvent.change(await screen.findByDisplayValue(from), { target: { value: to } });
}

let scrolledTo: Element[] = [];
const originalScrollIntoView = Element.prototype.scrollIntoView;

describe("MergedCsvPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    scrolledTo = [];
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
      scrolledTo.push(this);
    };
    qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("問題")]);
    qaNodeMocks.saveMergedQa.mockResolvedValue({ status: "ok" });
    qaNodeMocks.uploadImage.mockResolvedValue({ image_id: "img_123" });
  });

  afterEach(() => {
    Element.prototype.scrollIntoView = originalScrollIntoView;
    vi.useRealTimers();
  });

  describe("header", () => {
    it("names the category and where it sits, instead of the old editor title and internal id", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲"),
        makeRow("乙"),
        makeRow("丙", { hidden: true }),
      ]);
      const { container } = renderPane({
        nodeId: "qa_node_025",
        nodeLabel: "EVAK 沉水泵浦型錄",
        parentLabels: ["中文"],
      });

      expect((await screen.findByRole("heading")).textContent).toBe("中文 › EVAK 沉水泵浦型錄");
      expect(screen.getByText("訪客點到這個分類會看到這些問題")).toBeTruthy();
      expect(screen.getByText("顯示中 2 題，隱藏 1 題")).toBeTruthy();
      expect(container.textContent).not.toContain("合併檢視");
      expect(container.textContent).not.toContain("qa_node_025");
    });

    it("leaves out the hidden count when nothing is hidden", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      renderPane();

      expect(await screen.findByText("顯示中 3 題")).toBeTruthy();
    });

    it("tells the truth when the category itself cannot be reached by visitors", async () => {
      renderPane({ nodeHidden: true });

      expect(await screen.findByText(/這個分類目前隱藏中，訪客在選單看不到/)).toBeTruthy();
      expect(screen.queryByText("訪客點到這個分類會看到這些問題")).toBeNull();
    });

    it("shows where the content lives in plain words when it is one uploaded file", async () => {
      renderPane();

      expect(await screen.findByText("內容存放在：faq.csv")).toBeTruthy();
    });

    it("never shows the generated manual file path", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲", { source_file: "knowledge/qa/manual_root_1700000000.md" }),
      ]);
      const { container } = renderPane();

      await screen.findByDisplayValue("甲");
      expect(screen.queryByText(/內容存放在/)).toBeNull();
      expect(container.textContent).not.toContain("manual_");
    });

    it("labels each row with its file when a category has several, hiding generated names", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲", { source_file: "knowledge/qa/a.csv" }),
        makeRow("乙", { source_file: "knowledge/qa/manual_root.md" }),
      ]);
      const { container } = renderPane();

      await screen.findByDisplayValue("甲");
      expect(within(article("甲")).getByText("來自：a.csv")).toBeTruthy();
      expect(within(article("乙")).getByText("來自：自己輸入")).toBeTruthy();
      expect(container.textContent).not.toContain("manual_");
      expect(screen.queryByText(/內容存放在/)).toBeNull();
    });

    it("no longer offers the project-wide image cleanup here", async () => {
      renderPane();

      await screen.findByDisplayValue("問題");
      expect(screen.queryByRole("button", { name: /清理/ })).toBeNull();
    });

    it("keeps save and cancel at the top only, enabled once something changed", async () => {
      renderPane();

      await screen.findByDisplayValue("問題");
      expect(screen.queryByText("有未儲存的變更")).toBeNull();
      expect(saveButton().disabled).toBe(true);
      expect(cancelButton().disabled).toBe(true);

      await editQuestion("問題", "改過的問題");

      expect(screen.getByText("有未儲存的變更")).toBeTruthy();
      expect(saveButton().disabled).toBe(false);
      expect(cancelButton().disabled).toBe(false);
      // 操作要排在清單前面，不能又跑回底部被小助理蓋住。
      const position = saveButton().compareDocumentPosition(articles()[0]);
      expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("cancel puts everything back", async () => {
      const { onStatus } = renderPane();

      await editQuestion("問題", "改過的問題");
      fireEvent.click(cancelButton());

      expect(screen.getByDisplayValue("問題")).toBeTruthy();
      expect(screen.queryByText("有未儲存的變更")).toBeNull();
      expect(lastStatus(onStatus)).toBeNull();
    });
  });

  describe("adding questions", () => {
    it("adds to the end of the list, then scrolls to the new row and focuses its question", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(2));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.click(addButton());

      const rows = articles();
      expect(rows).toHaveLength(3);
      const newRow = rows[2];
      expect(within(newRow).getByText("第 3 題")).toBeTruthy();
      await waitFor(() => expect(scrolledTo).toContain(newRow));
      expect(document.activeElement).toBe(within(newRow).getByPlaceholderText("請輸入問題"));
    });

    it("sits above the list", async () => {
      renderPane();

      await screen.findByDisplayValue("問題");
      const position = addButton().compareDocumentPosition(articles()[0]);
      expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("keeps a new question at the end after saving by filing it with the last row", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲", { source_file: "knowledge/qa/a.csv" }),
        makeRow("乙", { source_file: "knowledge/qa/b.csv" }),
      ]);
      renderPane();

      await screen.findByDisplayValue("甲");
      fireEvent.click(addButton());
      const newRow = articles()[2];
      fireEvent.change(within(newRow).getByPlaceholderText("請輸入問題"), { target: { value: "新題" } });
      fireEvent.change(within(newRow).getByPlaceholderText("請輸入答案"), { target: { value: "新答" } });
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload()[2]).toMatchObject({ q: "新題", source_file: "knowledge/qa/b.csv" });
    });

    it("shows an explanation for an empty category instead of a fake blank question", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([]);
      renderPane();

      expect(await screen.findByText("這個分類還沒有問題")).toBeTruthy();
      expect(screen.queryByPlaceholderText("請輸入問題")).toBeNull();
      expect(screen.queryByRole("button", { name: /掛載來源/ })).toBeNull();
      expect(saveButton().disabled).toBe(true);
      expect(screen.queryByText(/顯示中/)).toBeNull();
    });

    it("mentions sub-categories when the category only holds those", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([]);
      renderPane({ childCategoryCount: 3 });

      expect(await screen.findByText(/底下的 3 個子分類/)).toBeTruthy();
    });

    it("starts an empty category from the new-question button, saved into its own file", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([]);
      renderPane();

      await screen.findByText("這個分類還沒有問題");
      fireEvent.click(addButton());

      const question = screen.getByPlaceholderText("請輸入問題");
      await waitFor(() => expect(document.activeElement).toBe(question));
      fireEvent.change(question, { target: { value: "第一題" } });
      fireEvent.change(screen.getByPlaceholderText("請輸入答案"), { target: { value: "答案" } });
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload()).toEqual([
        expect.objectContaining({
          index: "1",
          q: "第一題",
          source_file: "knowledge/qa/manual_root.md",
        }),
      ]);
    });
  });

  describe("saving", () => {
    function dragRow(from: string, to: string) {
      const dataTransfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
      const at = (event: Event) => {
        Object.defineProperty(event, "clientY", { value: 1 });
        return event;
      };
      const target = article(to);
      fireEvent.dragStart(article(from).querySelector("[draggable]") as HTMLElement, { dataTransfer });
      fireEvent(target, at(createEvent.dragOver(target, { dataTransfer })));
      fireEvent(target, at(createEvent.drop(target, { dataTransfer })));
    }

    it("saves dragged rows in their new order with index values matching the screen", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲", { index: "1" }),
        makeRow("乙", { index: "2" }),
        makeRow("丙", { index: "3" }),
      ]);
      renderPane();

      await screen.findByDisplayValue("甲");
      dragRow("甲", "丙");
      expect(questionValues()).toEqual(["乙", "丙", "甲"]);
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload().map((item) => [item.index, item.q])).toEqual([
        ["1", "乙"],
        ["2", "丙"],
        ["3", "甲"],
      ]);
    });

    it("renumbers from the screen even when the old numbers were not 1..N", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲", { index: "30" }),
        makeRow("乙", { index: "7" }),
      ]);
      renderPane();

      await editQuestion("甲", "甲改");
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload().map((item) => [item.index, item.q])).toEqual([
        ["1", "甲改"],
        ["2", "乙"],
      ]);
    });

    it("trims the fields and does not send the local row id", async () => {
      renderPane();

      await editQuestion("問題", "  前後有空白  ");
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload()[0].q).toBe("前後有空白");
      expect(savedPayload()[0]).not.toHaveProperty("_localId");
    });

    it("reports success in plain words through the shared message", async () => {
      const { onStatus, onSuccess } = renderPane();

      await editQuestion("問題", "改過的問題");
      fireEvent.click(saveButton());

      await waitFor(() => expect(onSuccess).toHaveBeenCalled());
      expect(onStatus).toHaveBeenCalledWith({
        type: "success",
        message: "已儲存，AI 和選單都會用新內容",
      });
    });

    it("stays on the list while re-reading after a save, so the scroll position is kept", async () => {
      renderPane();

      await editQuestion("問題", "改過的問題");
      const reload = deferred<MergedQaItem[]>();
      qaNodeMocks.fetchMergedQa.mockReturnValueOnce(reload.promise);
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.fetchMergedQa).toHaveBeenCalledTimes(2));
      expect(screen.queryByText("正在載入問題…")).toBeNull();
      expect(screen.getByDisplayValue("改過的問題")).toBeTruthy();

      await act(async () => reload.resolve([makeRow("改過的問題")]));
    });

    it("locks the fields while saving, since the re-read would overwrite anything typed", async () => {
      const save = deferred<{ status: string }>();
      qaNodeMocks.saveMergedQa.mockReturnValueOnce(save.promise);
      renderPane();

      await editQuestion("問題", "改過的問題");
      fireEvent.click(saveButton());

      expect((screen.getByDisplayValue("改過的問題") as HTMLTextAreaElement).matches(":disabled")).toBe(true);
      expect(saveButton().disabled).toBe(true);

      await act(async () => save.resolve({ status: "ok" }));
    });

    it("keeps the edits and says so when the save fails", async () => {
      qaNodeMocks.saveMergedQa.mockRejectedValueOnce(new Error("伺服器忙碌"));
      const { onStatus, onSuccess } = renderPane();

      await editQuestion("問題", "改過的問題");
      fireEvent.click(saveButton());

      await waitFor(() => expect(lastStatus(onStatus)).toEqual({ type: "error", message: "伺服器忙碌" }));
      expect(screen.getByDisplayValue("改過的問題")).toBeTruthy();
      expect(screen.getByText("有未儲存的變更")).toBeTruthy();
      expect(onSuccess).not.toHaveBeenCalled();
    });

    it("does not leave the screen looking unsaved when only the re-read fails", async () => {
      const { onStatus } = renderPane();

      await editQuestion("問題", "改過的問題");
      qaNodeMocks.fetchMergedQa.mockRejectedValueOnce(new Error("連線中斷"));
      fireEvent.click(saveButton());

      await waitFor(() => expect(lastStatus(onStatus)).toEqual({ type: "error", message: "連線中斷" }));
      expect(screen.queryByText("有未儲存的變更")).toBeNull();
      expect(screen.getByDisplayValue("改過的問題")).toBeTruthy();
    });

    it("names the question that is missing an answer and goes to it", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      const { onStatus } = renderPane();

      await screen.findByDisplayValue("問題1");
      const answer = within(article("問題2")).getByPlaceholderText("請輸入答案");
      fireEvent.change(answer, { target: { value: "  " } });
      fireEvent.click(saveButton());

      expect(lastStatus(onStatus)).toEqual({
        type: "error",
        message: "第 2 題：問題和答案都要填，填好再儲存。",
      });
      expect(qaNodeMocks.saveMergedQa).not.toHaveBeenCalled();
      await waitFor(() => expect(scrolledTo).toContain(article("問題2")));
      expect(document.activeElement).toBe(answer);
      expect(answer.getAttribute("aria-invalid")).toBe("true");
      expect(article("問題2").getAttribute("data-highlighted")).toBe("true");
    });

    it("lists every incomplete question, then stops marking one once it is filled", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      const { onStatus } = renderPane();

      await editQuestion("問題1", "");
      await editQuestion("問題3", "");
      fireEvent.click(saveButton());

      expect(lastStatus(onStatus).message).toBe("第 1、3 題：問題和答案都要填，填好再儲存。");
      const first = articles()[0];
      const question = within(first).getByPlaceholderText("請輸入問題");
      await waitFor(() => expect(document.activeElement).toBe(question));

      fireEvent.change(question, { target: { value: "補上了" } });
      expect(question.getAttribute("aria-invalid")).toBeNull();
    });

    it("shortens the list of numbers when many questions are incomplete", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(7));
      const { onStatus } = renderPane();

      await screen.findByDisplayValue("問題1");
      for (const field of screen.getAllByPlaceholderText("請輸入答案")) {
        fireEvent.change(field, { target: { value: "" } });
      }
      fireEvent.click(saveButton());

      expect(lastStatus(onStatus).message).toBe("第 1、2、3、4、5 等 7 題：問題和答案都要填，填好再儲存。");
    });

    // 實測後端：同一題存兩次，讀回來兩列都變成後面那個答案，前面的答案就不見了。
    it("refuses two identical questions, because the first answer would be lost", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      const { onStatus } = renderPane();

      await editQuestion("問題3", " 問題1 ");
      fireEvent.click(saveButton());

      expect(lastStatus(onStatus).message).toContain("第 1 題和第 3 題的問題一樣");
      expect(qaNodeMocks.saveMergedQa).not.toHaveBeenCalled();
      await waitFor(() => expect(scrolledTo).toContain(articles()[2]));
    });
  });

  describe("deleting", () => {
    it("removes the row right away, says how to undo it, and cancel brings it back", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      const { onStatus } = renderPane();

      await screen.findByDisplayValue("問題2");
      fireEvent.click(screen.getByRole("button", { name: "刪除第 2 題" }));

      expect(questionValues()).toEqual(["問題1", "問題3"]);
      expect(lastStatus(onStatus).message).toContain("已刪除第 2 題");
      expect(lastStatus(onStatus).message).toContain("取消變更");
      // 後面的列補上來，題號跟著變。
      expect(within(article("問題3")).getByText("第 2 題")).toBeTruthy();

      fireEvent.click(cancelButton());

      expect(questionValues()).toEqual(["問題1", "問題2", "問題3"]);
      expect(screen.queryByText("有未儲存的變更")).toBeNull();
    });

    it("saves without the deleted row and renumbers the rest", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload().map((item) => [item.index, item.q])).toEqual([
        ["1", "問題2"],
        ["2", "問題3"],
      ]);
    });

    it("keeps keyboard focus near the deleted row", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(2));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));

      await waitFor(() => expect(document.activeElement).toBe(article("問題2")));
      expect(scrolledTo).toHaveLength(0);
    });

    // 實測後端：清空分類後來源檔沒有重寫，下次讀取會長回一個新分類，題目全部回來。
    it("refuses to save an emptied category and points to deleting the category", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(1));
      const { onStatus } = renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));
      expect(await screen.findByText("題目都刪掉了，還沒有儲存")).toBeTruthy();
      await waitFor(() => expect(document.activeElement).toBe(addButton()));

      fireEvent.click(saveButton());

      expect(qaNodeMocks.saveMergedQa).not.toHaveBeenCalled();
      expect(lastStatus(onStatus).type).toBe("error");
      expect(lastStatus(onStatus).message).toContain("至少要留一題");
      expect(lastStatus(onStatus).message).toContain("「刪除」");

      fireEvent.click(cancelButton());
      expect(screen.getByDisplayValue("問題1")).toBeTruthy();
    });

    // 審查重現：分類的題目來自兩份檔案，刪光其中一份的題目後存檔，那份檔案會長回一個新分類。
    it("refuses to save when every question from one of several files was deleted", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲", { source_file: "knowledge/qa/a.csv" }),
        makeRow("乙", { source_file: "knowledge/qa/b.csv" }),
        makeRow("丙", { source_file: "knowledge/qa/b.csv" }),
      ]);
      const { onStatus } = renderPane();

      await screen.findByDisplayValue("甲");
      fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));
      fireEvent.click(saveButton());

      expect(qaNodeMocks.saveMergedQa).not.toHaveBeenCalled();
      expect(lastStatus(onStatus)).toEqual({
        type: "error",
        message: "「a.csv」的題目不能全部刪掉，至少留一題；要整份移除，請到左邊「文件」刪除那份檔案。想復原請按「取消變更」。",
      });
    });

    it("does not name the generated file when every typed-in question was deleted", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲", { source_file: "knowledge/qa/a.csv" }),
        makeRow("乙", { source_file: "knowledge/qa/manual_root.md" }),
      ]);
      const { onStatus } = renderPane();

      await screen.findByDisplayValue("乙");
      fireEvent.click(screen.getByRole("button", { name: "刪除第 2 題" }));
      fireEvent.click(saveButton());

      expect(qaNodeMocks.saveMergedQa).not.toHaveBeenCalled();
      expect(lastStatus(onStatus).message).toBe("自己輸入的題目不能全部刪掉，至少留一題。想復原請按「取消變更」。");
    });

    it("still saves when some questions of each file are left", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        makeRow("甲", { source_file: "knowledge/qa/a.csv" }),
        makeRow("乙", { source_file: "knowledge/qa/b.csv" }),
        makeRow("丙", { source_file: "knowledge/qa/b.csv" }),
      ]);
      renderPane();

      await screen.findByDisplayValue("甲");
      fireEvent.click(screen.getByRole("button", { name: "刪除第 2 題" }));
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload().map((item) => item.q)).toEqual(["甲", "丙"]);
    });

    it("reuses the original file when questions are added back after deleting them all", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("舊題", { source_file: "knowledge/qa/a.csv" })]);
      renderPane();

      await screen.findByDisplayValue("舊題");
      fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));
      fireEvent.click(addButton());
      fireEvent.change(screen.getByPlaceholderText("請輸入問題"), { target: { value: "新題" } });
      fireEvent.change(screen.getByPlaceholderText("請輸入答案"), { target: { value: "新答" } });
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload()).toEqual([
        expect.objectContaining({ q: "新題", source_file: "knowledge/qa/a.csv" }),
      ]);
    });
  });

  describe("searching", () => {
    it("only offers a search box above five questions", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(5));
      const { unmount } = renderPane();

      await screen.findByDisplayValue("問題1");
      expect(screen.queryByRole("searchbox")).toBeNull();
      unmount();

      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      renderPane();

      await screen.findByDisplayValue("問題1");
      expect(searchBox()).toBeTruthy();
    });

    it("matches questions and answers, ignoring case, and says how many it found", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([
        ...makeRows(5),
        makeRow("Warranty 怎麼算", { a: "看保固卡" }),
        makeRow("保固多久", { a: "這台的 WARRANTY 是兩年" }),
      ]);
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "warranty" } });

      expect(questionValues()).toEqual(["Warranty 怎麼算", "保固多久"]);
      expect(screen.getByText("找到 2 題")).toBeTruthy();
    });

    it("keeps each row's real number while filtered", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "問題6" } });

      expect(within(article("問題6")).getByText("第 6 題")).toBeTruthy();
    });

    it("explains an empty result and can clear it", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "沒有這個字" } });

      expect(screen.getByText("找不到符合「沒有這個字」的問題")).toBeTruthy();
      expect(screen.getByText("找到 0 題")).toBeTruthy();
      expect(screen.queryAllByRole("article")).toHaveLength(0);

      fireEvent.click(screen.getAllByRole("button", { name: "清除搜尋" })[0]);

      expect(questionValues()).toHaveLength(6);
      expect((searchBox() as HTMLInputElement).value).toBe("");
    });

    it("edits the right row while filtered, and saves the full list in its full order", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "問題6" } });
      expect(articles()).toHaveLength(1);

      fireEvent.change(screen.getByDisplayValue("問題6的答案"), { target: { value: "新的答案" } });
      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload().map((item) => [item.index, item.q, item.a])).toEqual([
        ["1", "問題1", "問題1的答案"],
        ["2", "問題2", "問題2的答案"],
        ["3", "問題3", "問題3的答案"],
        ["4", "問題4", "問題4的答案"],
        ["5", "問題5", "問題5的答案"],
        ["6", "問題6", "新的答案"],
      ]);
    });

    it("deletes the right row while filtered", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "問題4" } });
      fireEvent.click(screen.getByRole("button", { name: "刪除第 4 題" }));
      fireEvent.click(screen.getAllByRole("button", { name: "清除搜尋" })[0]);

      expect(questionValues()).toEqual(["問題1", "問題2", "問題3", "問題5", "問題6"]);
    });

    it("cannot be dragged while filtered, because the list on screen is not the full order", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      const { container } = renderPane();

      await screen.findByDisplayValue("問題1");
      expect(container.querySelectorAll("[draggable]")).toHaveLength(6);

      fireEvent.change(searchBox(), { target: { value: "問題" } });

      expect(articles()).toHaveLength(6);
      expect(container.querySelectorAll("[draggable]")).toHaveLength(0);
      expect(screen.getByText("搜尋時不能調整順序，清除搜尋後才能拖曳。")).toBeTruthy();

      fireEvent.click(screen.getByRole("button", { name: "清除搜尋" }));
      expect(container.querySelectorAll("[draggable]")).toHaveLength(6);
    });

    it("does not make a row disappear while typing in it", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([...makeRows(5), makeRow("保固多久", { a: "兩年" })]);
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "保固" } });
      fireEvent.change(within(article("保固多久")).getByPlaceholderText("請輸入問題"), {
        target: { value: "完全不同的字" },
      });

      expect(screen.getByDisplayValue("完全不同的字")).toBeTruthy();
      expect(screen.getByText("找到 1 題")).toBeTruthy();
    });

    it("clears the search when adding a question, so the new row can be seen", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "問題6" } });
      fireEvent.click(addButton());

      expect(articles()).toHaveLength(7);
      expect((searchBox() as HTMLInputElement).value).toBe("");
      await waitFor(() => expect(scrolledTo).toContain(articles()[6]));
    });

    it("clears the search to reach an incomplete question that it was hiding", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      const { onStatus } = renderPane();

      await editQuestion("問題2", "");
      fireEvent.change(searchBox(), { target: { value: "問題6" } });
      expect(articles()).toHaveLength(1);
      fireEvent.click(saveButton());

      expect(lastStatus(onStatus).message).toContain("第 2 題");
      expect(articles()).toHaveLength(6);
      await waitFor(() => expect(scrolledTo).toContain(articles()[1]));
    });

    it("keeps the box while a search is active even if deleting drops it to five rows", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "問題1" } });
      fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));

      expect((searchBox() as HTMLInputElement).value).toBe("問題1");
    });
  });

  describe("jumping to a question from the tree", () => {
    it("waits for the rows to load, then scrolls to the question and marks it briefly", async () => {
      const load = deferred<MergedQaItem[]>();
      qaNodeMocks.fetchMergedQa.mockReturnValueOnce(load.promise);
      renderPane({ focusQuestion: { question: "問題4" } });

      expect(scrolledTo).toHaveLength(0);
      await act(async () => load.resolve(makeRows(6)));

      await waitFor(() => expect(scrolledTo).toEqual([article("問題4")]));
      expect(article("問題4").getAttribute("data-highlighted")).toBe("true");
      expect(article("問題3").getAttribute("data-highlighted")).toBeNull();
    });

    it("removes the mark after a moment", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      const { update } = renderPane();
      await screen.findByDisplayValue("問題1");

      vi.useFakeTimers();
      update({ focusQuestion: { question: "問題2" } });
      expect(article("問題2").getAttribute("data-highlighted")).toBe("true");

      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(article("問題2").getAttribute("data-highlighted")).toBeNull();
    });

    it("scrolls again when the same question is clicked again", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      const { update } = renderPane({ focusQuestion: { question: "問題3" } });

      await waitFor(() => expect(scrolledTo).toHaveLength(1));
      update({ focusQuestion: { question: "問題3" } });

      await waitFor(() => expect(scrolledTo).toHaveLength(2));
    });

    it("does not scroll again just because the rows changed", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      renderPane({ focusQuestion: { question: "問題3" } });

      await waitFor(() => expect(scrolledTo).toHaveLength(1));
      await editQuestion("問題1", "改過");

      expect(scrolledTo).toHaveLength(1);
    });

    it("clears the search when it was hiding the question", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      const { update } = renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "問題6" } });
      update({ focusQuestion: { question: "問題2" } });

      expect((searchBox() as HTMLInputElement).value).toBe("");
      await waitFor(() => expect(scrolledTo).toEqual([article("問題2")]));
    });

    it("keeps the search when the question is among the results", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      const { update } = renderPane();

      await screen.findByDisplayValue("問題1");
      fireEvent.change(searchBox(), { target: { value: "問題2" } });
      update({ focusQuestion: { question: "問題2" } });

      expect((searchBox() as HTMLInputElement).value).toBe("問題2");
      await waitFor(() => expect(scrolledTo).toEqual([article("問題2")]));
    });

    it("finds the row whose question was edited but not saved, since the tree still has the old words", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      const { update } = renderPane();

      await editQuestion("問題2", "改過的問題");
      update({ focusQuestion: { question: "問題2" } });

      await waitFor(() => expect(scrolledTo).toEqual([article("改過的問題")]));
      expect(screen.getByDisplayValue("改過的問題")).toBeTruthy();
    });

    it("does nothing when the question is not in this category", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      renderPane({ focusQuestion: { question: "別的分類的題目" } });

      await screen.findByDisplayValue("問題1");
      expect(scrolledTo).toHaveLength(0);
    });
  });

  describe("unsaved changes", () => {
    function GuardProbe({ onLeave }: { onLeave: () => void }) {
      const { requestNavigation } = useNavigationGuard();
      return <button type="button" onClick={() => requestNavigation(onLeave)}>離開</button>;
    }

    function renderWithProbe(nodeId: string | null = "root") {
      const onLeave = vi.fn();
      const tree = (id: string | null) => (
        <NavigationGuardProvider>
          <MergedCsvPane nodeId={id} nodeLabel="Root" />
          <GuardProbe onLeave={onLeave} />
        </NavigationGuardProvider>
      );
      const utils = render(tree(nodeId));
      return { onLeave, showNode: (id: string | null) => utils.rerender(tree(id)) };
    }

    it("lets navigation through while nothing has changed", async () => {
      const { onLeave } = renderWithProbe();

      await screen.findByDisplayValue("問題");
      fireEvent.click(screen.getByRole("button", { name: "離開" }));

      expect(onLeave).toHaveBeenCalled();
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("asks before leaving once something changed", async () => {
      const { onLeave } = renderWithProbe();

      await editQuestion("問題", "改過的問題");
      fireEvent.click(screen.getByRole("button", { name: "離開" }));

      expect(within(await screen.findByRole("dialog")).getByText(/「快速問答」中的未儲存內容/)).toBeTruthy();
      expect(onLeave).not.toHaveBeenCalled();
    });

    it("stops asking after saving", async () => {
      const { onLeave } = renderWithProbe();

      await editQuestion("問題", "改過的問題");
      fireEvent.click(saveButton());
      await waitFor(() => expect(screen.queryByText("有未儲存的變更")).toBeNull());
      fireEvent.click(screen.getByRole("button", { name: "離開" }));

      expect(onLeave).toHaveBeenCalled();
    });

    it("stops asking once the editor is gone, so nothing stays blocked", async () => {
      const { onLeave, showNode } = renderWithProbe();

      await editQuestion("問題", "改過的問題");
      showNode(null);
      fireEvent.click(screen.getByRole("button", { name: "離開" }));

      expect(onLeave).toHaveBeenCalled();
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  describe("switching and loading", () => {
    it("shows the new category's rows even if the old request finishes later", async () => {
      const first = deferred<MergedQaItem[]>();
      const second = deferred<MergedQaItem[]>();
      qaNodeMocks.fetchMergedQa.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
      const { update } = renderPane({ nodeId: "a" });

      update({ nodeId: "b" });
      await act(async () => second.resolve([makeRow("乙分類的題目")]));
      await act(async () => first.resolve([makeRow("甲分類的題目")]));

      expect(screen.getByDisplayValue("乙分類的題目")).toBeTruthy();
      expect(screen.queryByDisplayValue("甲分類的題目")).toBeNull();
    });

    it("starts over when the category changes, dropping the search and the edits", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(6));
      const { update } = renderPane({ nodeId: "a" });

      await editQuestion("問題1", "改過的問題");
      fireEvent.change(searchBox(), { target: { value: "問題6" } });
      update({ nodeId: "b" });

      await screen.findByDisplayValue("問題1");
      expect((searchBox() as HTMLInputElement).value).toBe("");
      expect(screen.queryByText("有未儲存的變更")).toBeNull();
    });

    it("re-reads quietly when the refresh key changes", async () => {
      const { update } = renderPane({ refreshKey: 0 });
      await screen.findByDisplayValue("問題");

      qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("新內容")]);
      update({ refreshKey: 1 });

      expect(screen.queryByText("正在載入問題…")).toBeNull();
      expect(await screen.findByDisplayValue("新內容")).toBeTruthy();
    });

    it("uses the newest result when two re-reads of the same category overlap", async () => {
      const { update } = renderPane({ refreshKey: 0 });
      await screen.findByDisplayValue("問題");

      const older = deferred<MergedQaItem[]>();
      const newer = deferred<MergedQaItem[]>();
      qaNodeMocks.fetchMergedQa.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
      update({ refreshKey: 1 });
      update({ refreshKey: 2 });

      await act(async () => newer.resolve([makeRow("較新的內容")]));
      await act(async () => older.resolve([makeRow("較舊的內容")]));

      expect(screen.getByDisplayValue("較新的內容")).toBeTruthy();
      expect(screen.queryByDisplayValue("較舊的內容")).toBeNull();
    });

    // 讀取失敗時清單是空的：這時候能新增並儲存，就會用一題蓋掉整個分類。
    it("does not offer editing when the rows could not be read, and can retry", async () => {
      qaNodeMocks.fetchMergedQa.mockRejectedValueOnce(new Error("連線中斷"));
      renderPane();

      expect((await screen.findByRole("alert")).textContent).toContain("連線中斷");
      expect(screen.queryByRole("button", { name: "新增問題" })).toBeNull();
      expect(screen.queryByText("這個分類還沒有問題")).toBeNull();
      expect(saveButton().disabled).toBe(true);

      fireEvent.click(screen.getByRole("button", { name: "再試一次" }));

      expect(await screen.findByDisplayValue("問題")).toBeTruthy();
      expect(screen.queryByRole("alert")).toBeNull();
    });
  });

  describe("row details", () => {
    it("shows the referenced image as a thumbnail", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("PRP", { img: "PRP(1)" })]);
      renderPane();

      const image = await screen.findByRole("img", { name: "PRP的參考圖片" });
      expect(image.getAttribute("src")).toBe(
        "/api/v1/knowledge/qa/images/PRP(1)?project_id=default",
      );
    });

    it("says so when the image number does not lead to an image", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("PRP", { img: "打錯的編號" })]);
      renderPane();

      fireEvent.error(await screen.findByRole("img", { name: "PRP的參考圖片" }));

      expect(screen.getByText("找不到這張圖")).toBeTruthy();
    });

    it("uses the shared input style", async () => {
      renderPane();

      expect((await screen.findByDisplayValue("問題")).className).toContain("input");
    });

    it("toggles a question between shown and hidden, and explains what that means", async () => {
      renderPane();

      await screen.findByDisplayValue("問題");
      expect(screen.getByText(/「已隱藏」的問題不會出現在訪客的選單，但 AI 回答時還是會用/)).toBeTruthy();
      expect(within(article("問題")).getByText("隱藏這題")).toBeTruthy();

      fireEvent.click(screen.getByRole("button", { name: "第 1 題顯示中，按一下隱藏" }));

      expect(within(article("問題")).getByText("已隱藏 · 改回顯示")).toBeTruthy();
      expect(screen.getByRole("button", { name: "第 1 題已隱藏，按一下改成顯示" })).toBeTruthy();
      expect(screen.getByText("顯示中 0 題，隱藏 1 題")).toBeTruthy();

      fireEvent.click(saveButton());

      await waitFor(() => expect(qaNodeMocks.saveMergedQa).toHaveBeenCalled());
      expect(savedPayload()[0].hidden).toBe(true);
    });

    function pickFile(container: HTMLElement) {
      fireEvent.change(container.querySelector('input[type="file"]') as HTMLInputElement, {
        target: { files: [new File(["fake"], "qa.png", { type: "image/png" })] },
      });
    }

    it("uploads an image from a row and writes the returned number into that row", async () => {
      const { container, onStatus } = renderPane();

      await screen.findByDisplayValue("問題");
      fireEvent.click(screen.getByRole("button", { name: "第 1 題加圖片" }));
      fireEvent.click(screen.getByRole("button", { name: "第 1 題上傳圖片" }));
      pickFile(container);

      await waitFor(() => expect(qaNodeMocks.uploadImage).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(screen.getByPlaceholderText("圖片編號")).toHaveProperty("value", "img_123"));
      expect(lastStatus(onStatus)).toEqual({
        type: "success",
        message: "圖片已上傳，編號已經填好。按「儲存變更」才會生效。",
      });
      expect(screen.getByText("有未儲存的變更")).toBeTruthy();
    });

    it("writes the image to the row it was picked for, even if rows moved meanwhile", async () => {
      qaNodeMocks.fetchMergedQa.mockResolvedValue(makeRows(3));
      const upload = deferred<{ image_id: string }>();
      qaNodeMocks.uploadImage.mockReturnValueOnce(upload.promise);
      const { container } = renderPane();

      await screen.findByDisplayValue("問題3");
      fireEvent.click(screen.getByRole("button", { name: "第 3 題加圖片" }));
      fireEvent.click(screen.getByRole("button", { name: "第 3 題上傳圖片" }));
      pickFile(container);
      fireEvent.click(screen.getByRole("button", { name: "刪除第 1 題" }));

      await act(async () => upload.resolve({ image_id: "img_123" }));

      expect(within(article("問題3")).getByPlaceholderText("圖片編號")).toHaveProperty("value", "img_123");
    });

    it("does not save while an image is still uploading", async () => {
      const upload = deferred<{ image_id: string }>();
      qaNodeMocks.uploadImage.mockReturnValueOnce(upload.promise);
      const { container } = renderPane();

      await editQuestion("問題", "改過的問題");
      fireEvent.click(screen.getByRole("button", { name: "第 1 題加圖片" }));
      fireEvent.click(screen.getByRole("button", { name: "第 1 題上傳圖片" }));
      pickFile(container);

      await waitFor(() => expect(screen.getByText("上傳中…")).toBeTruthy());
      expect(saveButton().disabled).toBe(true);

      await act(async () => upload.resolve({ image_id: "img_123" }));
      expect(saveButton().disabled).toBe(false);
    });

    it("reports a failed upload and leaves the row alone", async () => {
      qaNodeMocks.uploadImage.mockRejectedValueOnce(new Error("不支援的圖片格式"));
      const { container, onStatus } = renderPane();

      await screen.findByDisplayValue("問題");
      fireEvent.click(screen.getByRole("button", { name: "第 1 題加圖片" }));
      fireEvent.click(screen.getByRole("button", { name: "第 1 題上傳圖片" }));
      pickFile(container);

      await waitFor(() =>
        expect(lastStatus(onStatus)).toEqual({ type: "error", message: "不支援的圖片格式" }));
      expect(screen.getByPlaceholderText("圖片編號")).toHaveProperty("value", "");
      expect(screen.queryByText("有未儲存的變更")).toBeNull();
    });
  });
});

describe("MergedCsvPane when an import updates the open category", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("shows the new questions when nothing is being edited", async () => {
    qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("舊題")]);
    const { rerender } = render(pane({ refreshKey: 0 }));
    await screen.findByDisplayValue("舊題");

    qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("舊題"), makeRow("新題")]);
    rerender(pane({ refreshKey: 1 }));

    expect(await screen.findByDisplayValue("新題")).toBeTruthy();
  });

  it("keeps unsaved edits and warns, then Cancel loads the new content", async () => {
    const onStatus = vi.fn();
    qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("舊題")]);
    const { rerender } = render(pane({ refreshKey: 0, onStatus }));
    fireEvent.change(await screen.findByDisplayValue("舊題的答案"), { target: { value: "我正在改" } });

    qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("舊題"), makeRow("新題")]);
    rerender(pane({ refreshKey: 1, onStatus }));

    await waitFor(() => expect(onStatus).toHaveBeenCalledWith(expect.objectContaining({
      type: "error",
      message: expect.stringContaining("剛匯入了新內容"),
    })));
    expect(screen.getByDisplayValue("我正在改")).toBeTruthy();
    expect(screen.queryByDisplayValue("新題")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "取消變更" }));

    expect(await screen.findByDisplayValue("新題")).toBeTruthy();
    expect(screen.queryByDisplayValue("我正在改")).toBeNull();
  });

  it("does not warn when an unrelated import left this category unchanged", async () => {
    const onStatus = vi.fn();
    qaNodeMocks.fetchMergedQa.mockResolvedValue([makeRow("舊題")]);
    const { rerender } = render(pane({ refreshKey: 0, onStatus }));
    fireEvent.change(await screen.findByDisplayValue("舊題的答案"), { target: { value: "我正在改" } });
    const callsBefore = qaNodeMocks.fetchMergedQa.mock.calls.length;
    onStatus.mockClear();

    rerender(pane({ refreshKey: 1, onStatus }));
    await waitFor(() => expect(qaNodeMocks.fetchMergedQa.mock.calls.length).toBe(callsBefore + 1));
    await act(async () => { await Promise.resolve(); });

    expect(onStatus).not.toHaveBeenCalledWith(expect.objectContaining({ type: "error" }));
    expect(screen.getByDisplayValue("我正在改")).toBeTruthy();
  });
});
