import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgePreviewQaFile } from "../../api";
import type { QaNode } from "../../hooks/useQaNodes";
import QaUploadReview, { type QaUploadReviewFileItem } from "./QaUploadReview";

const qaNodeMocks = vi.hoisted(() => ({ uploadImage: vi.fn() }));

vi.mock("../../hooks/useQaNodes", () => ({
  useQaNodes: () => qaNodeMocks,
}));

function makePreview(overrides: Partial<KnowledgePreviewQaFile> = {}): KnowledgePreviewQaFile {
  return {
    kind: "qa",
    target: "knowledge/qa/faq.md",
    existing: true,
    errors: [],
    duplicate_rows: 2,
    questions: [
      {
        question: "營業時間",
        status: "conflict",
        placement: ["中文", "服務", "營業時間"],
        language: "zh",
        old: { answer: "早上九點", image: "old.png", url: "" },
        new: { answer: "早上十點", image: "new.png", url: "" },
      },
      {
        question: "門票費用",
        status: "conflict",
        placement: ["中文", "服務", "營業時間"],
        language: "zh",
        old: { answer: "100 元", image: "", url: "" },
        new: { answer: "免費", image: "", url: "" },
      },
      {
        question: "停車資訊",
        status: "same",
        placement: ["中文", "服務"],
        language: "zh",
      },
      {
        question: "接駁車",
        status: "new",
        placement: ["中文", "交通"],
        language: "zh",
      },
    ],
    missing_images: [],
    notes: [],
    ...overrides,
  };
}

function makeFile(
  rawPath = "faq.csv",
  preview: KnowledgePreviewQaFile = makePreview(),
): QaUploadReviewFileItem {
  return {
    rawPath,
    name: rawPath,
    itemId: `item-${rawPath}`,
    preview,
  };
}

function makeNode(id: string, label: string, children: QaNode[] = []): QaNode {
  return {
    node_id: id,
    label,
    parent_ids: [],
    child_ids: children.map((c) => c.node_id),
    order: 1,
    hidden: false,
    qa_entries: [],
    children,
  };
}

describe("QaUploadReview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qaNodeMocks.uploadImage.mockResolvedValue({ image_id: "uploaded_99.png" });
  });

  it("counts all five outcomes and waits for explicit choices for every conflict", () => {
    const onConfirm = vi.fn();
    const existingTree = [
      makeNode("zh", "中文", [makeNode("service", "服務")]),
    ];

    render(
      <QaUploadReview
        files={[makeFile()]}
        nodesTree={existingTree}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    const group1 = screen.getByRole("radiogroup", { name: "營業時間 的處理方式" });
    const group2 = screen.getByRole("radiogroup", { name: "門票費用 的處理方式" });
    for (const radio of screen.getAllByRole<HTMLInputElement>("radio")) {
      expect(radio.checked).toBe(false);
    }
    const importButton = screen.getByRole<HTMLButtonElement>("button", { name: "匯入" });
    expect(importButton.disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("還有 2 題沒選");
    expect(screen.getByText("新題目 1、重複（答案相同）1、重複（答案不同）2、檔案內重複 2、格式錯誤 0")).toBeTruthy();

    // 分類樹預覽：中文、服務已存在；營業時間、交通標「新」
    const tree = screen.getByRole("list", { name: "faq.csv 分類預覽" });
    const items = within(tree).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "中文",
      "服務1 題",
      "營業時間新2 題",
      "交通新1 題",
    ]);

    fireEvent.click(within(group1).getByLabelText("覆蓋"));
    expect(importButton.disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("還有 1 題沒選");
    fireEvent.click(within(group2).getByLabelText("保留原本"));
    expect(importButton.disabled).toBe(false);
    fireEvent.click(importButton);

    expect(onConfirm).toHaveBeenCalledWith(["faq.csv"], {
      "faq.csv": {
        conflicts: {
          營業時間: "overwrite",
          門票費用: "keep",
        },
        images: {},
      },
    });
  });

  it("bulk overwrite covers multiple files and an individual choice can override it", () => {
    const onConfirm = vi.fn();
    render(
      <QaUploadReview
        files={[makeFile(), makeFile("more.csv")]}
        nodesTree={[]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重複的全部覆蓋" }));
    const first = screen.getByRole("article", { name: "檢查 faq.csv" });
    const group = within(first).getByRole("radiogroup", { name: "門票費用 的處理方式" });
    fireEvent.click(within(group).getByLabelText("兩題都留（新的會先隱藏）"));
    fireEvent.click(screen.getByRole("button", { name: "匯入" }));

    expect(onConfirm).toHaveBeenCalledWith(["faq.csv", "more.csv"], {
      "faq.csv": { conflicts: { 營業時間: "overwrite", 門票費用: "both" }, images: {} },
      "more.csv": { conflicts: { 營業時間: "overwrite", 門票費用: "overwrite" }, images: {} },
    });
  });

  it("does not wait for choices in a file left out of the import", () => {
    const onConfirm = vi.fn();
    render(
      <QaUploadReview
        files={[makeFile(), makeFile("more.csv")]}
        nodesTree={[]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("status").textContent).toBe("還有 4 題沒選");
    fireEvent.click(screen.getByRole("checkbox", { name: "匯入 more.csv" }));
    expect(screen.getByRole("status").textContent).toBe("還有 2 題沒選");
    const first = screen.getByRole("article", { name: "檢查 faq.csv" });
    for (const question of ["營業時間", "門票費用"]) {
      const group = within(first).getByRole("radiogroup", { name: `${question} 的處理方式` });
      fireEvent.click(within(group).getByLabelText("保留原本"));
    }
    fireEvent.click(screen.getByRole("button", { name: "匯入" }));

    expect(onConfirm).toHaveBeenCalledWith(["faq.csv"], {
      "faq.csv": { conflicts: { 營業時間: "keep", 門票費用: "keep" }, images: {} },
    });
  });

  it("bulk keep selects all conflicts and highlights only differing characters on both sides", () => {
    render(<QaUploadReview files={[makeFile()]} nodesTree={[]} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText("九", { selector: "mark" })).toBeTruthy();
    expect(screen.getByText("十", { selector: "mark" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重複的全部保留原本" }));
    for (const choice of screen.getAllByRole<HTMLInputElement>("radio", { name: "保留原本" })) {
      expect(choice.checked).toBe(true);
    }
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "匯入" }).disabled).toBe(false);
  });

  it("disables importing a file that has format errors", () => {
    const onConfirm = vi.fn();
    const badFile = makeFile(
      "bad.csv",
      makePreview({
        errors: ["「Q1」有第二層但沒有第一層。改好後重新上傳"],
      }),
    );

    render(
      <QaUploadReview
        files={[badFile]}
        nodesTree={[]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText("「Q1」有第二層但沒有第一層。改好後重新上傳")).toBeTruthy();
    expect(screen.getByText("請改好檔案後重新上傳")).toBeTruthy();
    const checkbox = screen.getByRole("checkbox", { name: "匯入 bad.csv" }) as HTMLInputElement;
    expect(checkbox.disabled).toBe(true);
    expect(checkbox.checked).toBe(false);

    const importBtn = screen.getByRole("button", { name: "匯入" }) as HTMLButtonElement;
    expect(importBtn.disabled).toBe(true);
    fireEvent.click(importBtn);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("uploads a missing image and includes its image_id in decisions.images", async () => {
    const onConfirm = vi.fn();
    const fileWithMissing = makeFile(
      "faq.csv",
      makePreview({
        questions: [
          {
            question: "平面圖在哪裡？",
            status: "new",
            placement: ["faq"],
            language: "zh",
          },
        ],
        missing_images: [{ image: "map.png", questions: ["平面圖在哪裡？"] }],
      }),
    );

    render(
      <QaUploadReview
        files={[fileWithMissing]}
        nodesTree={[]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText("沒補傳也可以匯入，那幾題就沒有圖片。")).toBeTruthy();
    expect(screen.getByText("用到這張圖的題目：平面圖在哪裡？")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "補傳圖片" }));
    fireEvent.change(screen.getByTestId("qa-review-image-input"), {
      target: { files: [new File(["img"], "map.png", { type: "image/png" })] },
    });

    await waitFor(() => expect(qaNodeMocks.uploadImage).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("img", { name: "map.png" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "匯入" }));

    expect(onConfirm).toHaveBeenCalledWith(["faq.csv"], {
      "faq.csv": {
        conflicts: {},
        images: { "map.png": "uploaded_99.png" },
      },
    });
  });

  it("calls onCancel without importing when clicking 取消", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    render(
      <QaUploadReview
        files={[makeFile()]}
        nodesTree={[]}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("names a category made from the file name without the file name for a vendor", () => {
    const preview = makePreview({
      target: "knowledge/qa/menu.md",
      existing: false,
      duplicate_rows: 0,
      questions: [{ question: "菜單", status: "new", placement: ["中文", "menu"], language: "zh" }],
    });
    render(
      <QaUploadReview
        vendor
        files={[makeFile("menu.csv", preview)]}
        nodesTree={[makeNode("zh", "中文")]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const placement = screen.getByRole("list", { name: "問答表 1 分類預覽" });
    expect(within(placement).getByText("問答表 1的題目")).toBeTruthy();
    expect(within(placement).getByText("新")).toBeTruthy();
    expect(within(placement).queryByText("menu")).toBeNull();
  });
});
