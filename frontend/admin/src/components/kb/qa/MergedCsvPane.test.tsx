import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MergedCsvPane from "./MergedCsvPane";

const qaNodeMocks = vi.hoisted(() => ({
  fetchMergedQa: vi.fn(),
  saveMergedQa: vi.fn(),
  uploadImage: vi.fn(),
  cleanupImages: vi.fn(),
}));

vi.mock("../../../hooks/useQaNodes", () => ({
  useQaNodes: () => qaNodeMocks,
}));

describe("MergedCsvPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qaNodeMocks.fetchMergedQa.mockResolvedValue([
      {
        index: "1",
        q: "問題",
        a: "答案",
        img: "",
        url: "",
        source_file: "knowledge/qa/faq.md",
        hidden: false,
      },
    ]);
    qaNodeMocks.saveMergedQa.mockResolvedValue({ status: "ok" });
    qaNodeMocks.uploadImage.mockResolvedValue({ image_id: "img_123" });
    qaNodeMocks.cleanupImages.mockResolvedValue({ deleted_files: [] });
  });

  it("uploads an image from a row and writes the returned image id into the row", async () => {
    const { container } = render(<MergedCsvPane nodeId="root" nodeLabel="Root" />);

    expect(await screen.findByDisplayValue("問題")).toBeTruthy();
    fireEvent.click(screen.getByTitle("上傳圖片並填入 ID"));

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["fake"], "qa.png", { type: "image/png" })] },
    });

    await waitFor(() => expect(qaNodeMocks.uploadImage).toHaveBeenCalledTimes(1));
    expect(screen.getByPlaceholderText("圖片 ID")).toHaveProperty("value", "img_123");
    expect(await screen.findByText("圖片已上傳（ID：img_123），請記得儲存變更。")).toBeTruthy();
  });

  it("opens the attach source flow from the pane and does not mention the removed upload dialog", async () => {
    qaNodeMocks.fetchMergedQa.mockResolvedValue([]);
    const onOpenAttachSource = vi.fn();

    render(
      <MergedCsvPane
        nodeId="root"
        nodeLabel="Root"
        onOpenAttachSource={onOpenAttachSource}
      />,
    );

    expect(await screen.findByText("此節點尚無任何問答數據")).toBeTruthy();
    expect(screen.queryByText(/上傳對話框/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /掛載來源/ }));

    expect(onOpenAttachSource).toHaveBeenCalledTimes(1);
  });
});
