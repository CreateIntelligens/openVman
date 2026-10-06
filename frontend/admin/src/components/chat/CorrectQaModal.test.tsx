import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MergedQaItem } from "../../hooks/useQaNodes";
import CorrectQaModal, { applyCorrection } from "./CorrectQaModal";

const qaApi = vi.hoisted(() => ({
  fetchTree: vi.fn(),
  fetchMergedQa: vi.fn(),
  saveMergedQa: vi.fn(),
}));

vi.mock("../../hooks/useQaNodes", () => ({
  useQaNodes: () => ({
    nodesTree: [
      {
        node_id: "clinic",
        label: "門診",
        parent_ids: [],
        child_ids: ["hours"],
        order: 1,
        hidden: false,
        qa_entries: [],
        children: [
          {
            node_id: "hours",
            label: "時間",
            parent_ids: ["clinic"],
            child_ids: [],
            order: 1,
            hidden: false,
            qa_entries: [],
            children: [],
          },
        ],
      },
    ],
    loading: false,
    error: null,
    ...qaApi,
  }),
}));

const existing: MergedQaItem[] = [
  {
    index: "1",
    q: "掛號要帶什麼？",
    a: "健保卡",
    img: "",
    url: "",
    source_file: "knowledge/qa/faq.csv",
    hidden: false,
  },
];

function renderModal() {
  const onClose = vi.fn();
  render(
    <CorrectQaModal
      open
      question="門診幾點開始？"
      answer="錯的答案"
      onClose={onClose}
    />,
  );
  return { onClose };
}

describe("CorrectQaModal", () => {
  beforeEach(() => {
    qaApi.fetchTree.mockReset().mockResolvedValue([]);
    qaApi.fetchMergedQa.mockReset().mockResolvedValue(existing);
    qaApi.saveMergedQa.mockReset().mockResolvedValue({ status: "ok" });
  });

  it("prefills the question and AI answer and lists nested nodes", () => {
    renderModal();

    expect((screen.getByLabelText("問題") as HTMLTextAreaElement).value).toBe("門診幾點開始？");
    expect((screen.getByLabelText("正確答案") as HTMLTextAreaElement).value).toBe("錯的答案");
    expect(screen.getByRole("option", { name: "門診 / 時間" })).not.toBeNull();
    expect(qaApi.fetchTree).toHaveBeenCalled();
  });

  it("saves the edited answer into the chosen node through the merged QA API", async () => {
    renderModal();

    fireEvent.change(screen.getByLabelText("存到問答節點"), { target: { value: "hours" } });
    fireEvent.change(screen.getByLabelText("正確答案"), { target: { value: " 早上八點半 " } });
    fireEvent.click(screen.getByRole("button", { name: /儲存/ }));

    await waitFor(() => expect(qaApi.saveMergedQa).toHaveBeenCalledTimes(1));
    expect(qaApi.fetchMergedQa).toHaveBeenCalledWith("hours");
    const [nodeId, rows] = qaApi.saveMergedQa.mock.calls[0] as [string, MergedQaItem[]];
    expect(nodeId).toBe("hours");
    expect(rows[0]).toEqual({
      q: "掛號要帶什麼？",
      a: "健保卡",
      img: "",
      url: "",
      source_file: "knowledge/qa/faq.csv",
      hidden: false,
    });
    expect(rows[1]).toMatchObject({ q: "門診幾點開始？", a: "早上八點半", hidden: true });
    expect(rows[1].source_file).toMatch(/^knowledge\/qa\/manual_hours_\d+\.md$/);
    expect(await screen.findByRole("status")).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("門診 / 時間");
  });

  it("shows the error and keeps the dialog open when saving fails", async () => {
    qaApi.saveMergedQa.mockRejectedValue(new Error("節點不存在"));
    const { onClose } = renderModal();

    fireEvent.click(screen.getByRole("button", { name: /儲存/ }));

    expect((await screen.findByRole("alert")).textContent).toContain("節點不存在");
    expect(onClose).not.toHaveBeenCalled();
    expect((screen.getByLabelText("正確答案") as HTMLTextAreaElement).value).toBe("錯的答案");
  });

  it("disables saving when the answer is empty", () => {
    renderModal();

    fireEvent.change(screen.getByLabelText("正確答案"), { target: { value: "   " } });
    expect((screen.getByRole("button", { name: /儲存/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("applyCorrection", () => {
  it("updates the answer in place when the question already exists", () => {
    const rows = applyCorrection(existing, "clinic", { q: "掛號要帶什麼？", a: "健保卡與身分證", hidden: true });

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ a: "健保卡與身分證", hidden: false, source_file: "knowledge/qa/faq.csv" });
    expect(rows[0]).not.toHaveProperty("index");
  });

  it("appends to the node's existing manual correction file", () => {
    const withManual: MergedQaItem[] = [
      ...existing,
      { q: "舊修正", a: "答", source_file: "knowledge/qa/manual_clinic_100.md" },
    ];

    const rows = applyCorrection(withManual, "clinic", { q: "新問題", a: "新答案", hidden: false }, 200);

    expect(rows[2]).toMatchObject({ q: "新問題", source_file: "knowledge/qa/manual_clinic_100.md", hidden: false });
  });
});
