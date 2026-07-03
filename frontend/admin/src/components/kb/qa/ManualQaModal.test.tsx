import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MergedQaItem, QaNode } from "../../../hooks/useQaNodes";
import ManualQaModal from "./ManualQaModal";

const node: QaNode = {
  node_id: "root",
  label: "Root",
  parent_ids: [],
  child_ids: [],
  order: 1,
  hidden: false,
  qa_entries: [],
};

const existingMerged: MergedQaItem[] = [
  {
    index: "1",
    q: "既有問題",
    a: "既有答案",
    img: "",
    url: "",
    source_file: "knowledge/qa/faq.md",
    hidden: false,
  },
];

function renderModal(overrides: Partial<Parameters<typeof ManualQaModal>[0]> = {}) {
  const defaults = {
    open: true,
    node,
    onFetchMergedQa: vi.fn().mockResolvedValue(existingMerged),
    onSaveMergedQa: vi.fn().mockResolvedValue({ status: "ok" }),
    onUploadImage: vi.fn().mockResolvedValue({ image_id: "img-1.png" }),
    onDeleteImage: vi.fn().mockResolvedValue({ status: "ok" }),
    onClose: vi.fn(),
    onSuccess: vi.fn(),
  };
  render(<ManualQaModal {...defaults} {...overrides} />);
  return defaults;
}

describe("ManualQaModal", () => {
  it("disables submit until a question is entered", () => {
    renderModal();
    const submit = screen.getByRole("button", { name: /送出/ });
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("問題（必填）"), {
      target: { value: "新問題" },
    });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
  });

  it("appends manual rows to existing merged entries under knowledge/qa/", async () => {
    const props = renderModal();

    fireEvent.change(screen.getByPlaceholderText("問題（必填）"), {
      target: { value: " 新問題 " },
    });
    fireEvent.change(screen.getByPlaceholderText("答案"), {
      target: { value: "新答案" },
    });
    fireEvent.click(screen.getByLabelText("顯示為預設問題"));
    fireEvent.click(screen.getByRole("button", { name: /送出/ }));

    await waitFor(() => expect(props.onSaveMergedQa).toHaveBeenCalledTimes(1));
    const [nodeId, rows] = props.onSaveMergedQa.mock.calls[0];
    expect(nodeId).toBe("root");
    expect(rows).toHaveLength(2);
    expect(rows[0]).not.toHaveProperty("index");
    expect(rows[0].q).toBe("既有問題");

    const added = rows[1];
    expect(added.q).toBe("新問題");
    expect(added.a).toBe("新答案");
    expect(added.hidden).toBe(true);
    expect(added.source_file).toMatch(/^knowledge\/qa\/manual_root_\d+\.md$/);

    expect(props.onSuccess).toHaveBeenCalledWith(1);
    expect(props.onClose).toHaveBeenCalled();
  });

  it("adds and removes question rows", () => {
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: /新增一題/ }));
    expect(screen.getAllByPlaceholderText("問題（必填）")).toHaveLength(2);

    fireEvent.click(screen.getAllByTitle("移除此題")[0]);
    expect(screen.getAllByPlaceholderText("問題（必填）")).toHaveLength(1);
  });

  it("rolls back uploaded images when saving fails", async () => {
    const props = renderModal({
      onSaveMergedQa: vi.fn().mockRejectedValue(new Error("save failed")),
    });

    fireEvent.change(screen.getByPlaceholderText("問題（必填）"), {
      target: { value: "有圖問題" },
    });

    const file = new File(["img"], "photo.png", { type: "image/png" });
    fireEvent.click(screen.getByTitle("選擇圖片（送出時上傳）"));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    fireEvent.click(screen.getByRole("button", { name: /送出/ }));

    await waitFor(() => expect(props.onDeleteImage).toHaveBeenCalledWith("img-1.png"));
    expect(props.onUploadImage).toHaveBeenCalledTimes(1);
    expect(props.onClose).not.toHaveBeenCalled();
    expect(await screen.findByText(/save failed|手動新增問答失敗/)).toBeTruthy();
  });
});
