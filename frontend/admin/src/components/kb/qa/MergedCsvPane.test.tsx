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

  it("starts an empty node with one editable row and exposes no attach-source action", async () => {
    qaNodeMocks.fetchMergedQa.mockResolvedValue([]);

    render(<MergedCsvPane nodeId="root" nodeLabel="Root" />);

    expect(await screen.findByPlaceholderText("請輸入問題")).toBeTruthy();
    expect(screen.getByPlaceholderText("請輸入答案")).toBeTruthy();
    expect(screen.queryByText("此節點尚無任何問答數據")).toBeNull();
    expect(screen.queryByRole("button", { name: /掛載來源/ })).toBeNull();
  });

  it("keeps focused QA cells readable in dark mode", async () => {
    render(<MergedCsvPane nodeId="root" nodeLabel="Root" />);

    const question = await screen.findByDisplayValue("問題");

    expect(question.className).toContain("dark:focus:bg-slate-950/70");
    expect(question.className).not.toContain("dark:focus:bg-slate-850");
  });

  it("shows the referenced image as a thumbnail", async () => {
    qaNodeMocks.fetchMergedQa.mockResolvedValue([
      {
        index: "1",
        q: "PRP 有哪些生長因子？",
        a: "答案",
        img: "PRP(1)",
        url: "",
        source_file: "knowledge/qa/prp.csv",
        hidden: false,
      },
    ]);

    render(<MergedCsvPane nodeId="root" nodeLabel="Root" />);

    const image = await screen.findByRole("img", { name: /PRP 有哪些生長因子/ });
    expect(image.getAttribute("src")).toBe(
      "/api/knowledge/qa/images/PRP(1)?project_id=default",
    );
  });
});
