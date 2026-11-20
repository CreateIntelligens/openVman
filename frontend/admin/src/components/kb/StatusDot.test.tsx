import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { KnowledgeDocumentSummary } from "../../api";
import StatusDot, {
  documentStatusLabel,
  QA_SYNC_FAILED_HINT,
  QaSyncStatusBadge,
  QaSyncStatusDot,
} from "./StatusDot";

function documentWith(
  fields: Partial<KnowledgeDocumentSummary>,
): KnowledgeDocumentSummary {
  return fields as KnowledgeDocumentSummary;
}

describe("documentStatusLabel", () => {
  it.each([
    [{ enabled: true, is_indexed: true, is_indexable: true }, "可被搜尋"],
    [{ enabled: true, is_indexed: false, is_indexable: true }, "處理中"],
    [{ enabled: true, is_indexed: false, is_indexable: false }, "不會被搜尋"],
    // 停用優先：還在索引裡也不算可被搜尋。
    [{ enabled: false, is_indexed: true, is_indexable: true }, "已停用"],
    [{ enabled: false, is_indexed: false, is_indexable: false }, "已停用"],
  ])("describes document status %#", (fields, label) => {
    expect(documentStatusLabel(documentWith(fields))).toBe(label);
  });

  it("treats a missing enabled flag as enabled", () => {
    expect(
      documentStatusLabel(documentWith({ is_indexed: true, is_indexable: true })),
    ).toBe("可被搜尋");
  });
});

describe("StatusDot", () => {
  it("shows nothing for a normal searchable document", () => {
    const { container } = render(
      <StatusDot
        doc={documentWith({ enabled: true, is_indexed: true, is_indexable: true })}
      />,
    );

    expect(container.textContent).toBe("");
    expect(container.firstChild).toBeNull();
  });

  it.each([
    [{ enabled: true, is_indexed: false, is_indexable: true }, "處理中"],
    [{ enabled: false, is_indexed: true, is_indexable: true }, "已停用"],
    [{ enabled: true, is_indexed: false, is_indexable: false }, "不會被搜尋"],
  ])("writes out the status that needs attention %#", (fields, label) => {
    render(<StatusDot doc={documentWith(fields)} />);

    expect(screen.getByText(label)).toBeTruthy();
  });
});

describe("QaSyncStatusBadge", () => {
  it("renders synced and updating labels with theme color dots and no failure hint", () => {
    const { rerender } = render(<QaSyncStatusBadge status="synced" />);
    expect(screen.getByText("已同步")).toBeTruthy();
    expect(screen.queryByText(QA_SYNC_FAILED_HINT)).toBeNull();

    rerender(<QaSyncStatusBadge status="updating" />);
    expect(screen.getByText("更新中")).toBeTruthy();
    expect(screen.queryByText(QA_SYNC_FAILED_HINT)).toBeNull();
  });

  it("renders 同步失敗 and the inline explanation text directly", () => {
    render(<QaSyncStatusBadge status="failed" />);

    expect(screen.getByText("同步失敗")).toBeTruthy();
    expect(
      screen.getByText("AI 暫時查不到這個分類的最新內容，請稍後再試，持續失敗請聯絡專人。"),
    ).toBeTruthy();
  });
});

describe("QaSyncStatusDot", () => {
  it("renders nothing for synced categories", () => {
    const { container } = render(<QaSyncStatusDot status="synced" />);
    expect(container.firstChild).toBeNull();
  });

  it.each([
    ["updating", "更新中", "bg-warn"],
    ["failed", "同步失敗", "bg-danger"],
  ] as const)("renders a themed dot with aria-label for %s", (status, label, colorClass) => {
    render(<QaSyncStatusDot status={status} />);

    const dot = screen.getByRole("img", { name: label });
    expect(dot.getAttribute("aria-label")).toBe(label);
    expect(dot.className).toContain(colorClass);
  });
});
