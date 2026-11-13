import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAllQuestions } from "../../../api/knowledge";
import { question, sample } from "./fixtures";
import QuestionsView, { QUESTIONS_PAGE_SIZE } from "./QuestionsView";

vi.mock("../../../api/knowledge", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../api/knowledge")>()),
  fetchAllQuestions: vi.fn(),
}));

const fetchMock = vi.mocked(fetchAllQuestions);

function renderView() {
  const onOpenCategory = vi.fn();
  const onOpenDocument = vi.fn();
  render(<QuestionsView projectId="demo" onOpenCategory={onOpenCategory} onOpenDocument={onOpenDocument} />);
  return { onOpenCategory, onOpenDocument };
}

function rowFor(text: string): HTMLElement {
  return screen.getByText(text).closest("li") as HTMLElement;
}

describe("QuestionsView", () => {
  beforeEach(() => fetchMock.mockReset());

  it("lists every question with its categories, states and source, and counts options", async () => {
    fetchMock.mockResolvedValue(sample());
    renderView();

    expect(await screen.findByText("共 7 題")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("demo");
    const parking = rowFor("Parking?");
    expect(within(parking).getByRole("button", { name: "打開分類 中文 › 服務" })).toBeTruthy();
    expect(within(parking).getByRole("button", { name: "打開分類 English" })).toBeTruthy();
    expect(within(parking).getByText("有圖片")).toBeTruthy();
    expect(within(rowFor("沒掛上？")).getByText("不在選單上（還沒放進分類）")).toBeTruthy();
    expect(within(rowFor("選單題？")).getByText("（只在選單上，點了交給 AI 回答）")).toBeTruthy();
    expect(within(rowFor("自己加的？")).getByText("自己輸入")).toBeTruthy();

    fireEvent.click(screen.getByRole("combobox", { name: "依語言篩選" }));
    expect(screen.getByRole("option", { name: "English（2）" })).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole("option", { name: "English（2）" }));

    expect(screen.getByText("共 7 題，符合 2 題")).toBeTruthy();
    expect(screen.queryByText("營業時間？")).toBeNull();
  });

  it("searches every question, not just the ones on screen", async () => {
    const many = Array.from({ length: QUESTIONS_PAGE_SIZE + 5 }, (_, index) =>
      question({ id: `q${index}`, question: `題目 ${index}` }));
    fetchMock.mockResolvedValue({ ...sample(), questions: many });
    renderView();

    expect(await screen.findByText(`共 ${many.length} 題`)).toBeTruthy();
    expect(screen.queryByText(`題目 ${QUESTIONS_PAGE_SIZE + 4}`)).toBeNull();
    expect(screen.getByRole("button", { name: "再顯示 5 題（還有 5 題）" })).toBeTruthy();

    fireEvent.change(screen.getByRole("searchbox", { name: "搜尋題目或答案" }), {
      target: { value: `題目 ${QUESTIONS_PAGE_SIZE + 4}` },
    });

    expect(screen.getByText(`題目 ${QUESTIONS_PAGE_SIZE + 4}`)).toBeTruthy();
    expect(screen.getByText(`共 ${many.length} 題，符合 1 題`)).toBeTruthy();
  });

  it("opens the first category for a row, any category from its tag, and the document when off the menu", async () => {
    fetchMock.mockResolvedValue(sample());
    const { onOpenCategory, onOpenDocument } = renderView();
    await screen.findByText("共 7 題");

    fireEvent.click(screen.getByText("Parking?"));
    expect(onOpenCategory).toHaveBeenLastCalledWith("svc", "Parking?");

    fireEvent.click(within(rowFor("Parking?")).getByRole("button", { name: "打開分類 English" }));
    expect(onOpenCategory).toHaveBeenLastCalledWith("en", "Parking?");

    fireEvent.click(screen.getByText("沒掛上？"));
    expect(onOpenDocument).toHaveBeenCalledWith("knowledge/qa/faq.csv");
  });

  it("explains an empty project and a failed load", async () => {
    fetchMock.mockResolvedValueOnce({ categories: [], questions: [] });
    renderView();
    expect(await screen.findByText(/還沒有快速問答的題目/)).toBeTruthy();
  });

  it("offers a retry when the list cannot be read", async () => {
    fetchMock.mockRejectedValueOnce(new Error("連不上")).mockResolvedValueOnce(sample());
    renderView();

    expect(await screen.findByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "再試一次" }));
    await waitFor(() => expect(screen.getByText("共 7 題")).toBeTruthy());
  });
});
