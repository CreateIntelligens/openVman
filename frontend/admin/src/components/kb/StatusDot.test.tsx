import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { KnowledgeDocumentSummary } from "../../api";
import StatusDot, { documentStatusLabel } from "./StatusDot";

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
