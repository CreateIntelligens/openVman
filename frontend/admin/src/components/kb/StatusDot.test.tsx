import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { KnowledgeDocumentSummary } from "../../api";
import StatusDot from "./StatusDot";

function documentWith(
  fields: Partial<KnowledgeDocumentSummary>,
): KnowledgeDocumentSummary {
  return fields as KnowledgeDocumentSummary;
}

describe("StatusDot", () => {
  it.each([
    [{ is_indexed: true, is_indexable: true }, "已索引"],
    [{ is_indexed: false, is_indexable: true }, "待處理"],
    [{ is_indexed: false, is_indexable: false }, "已排除"],
  ])("announces document status %#", (fields, label) => {
    render(<StatusDot doc={documentWith(fields)} />);
    expect(screen.getByRole("img", { name: label })).toBeTruthy();
  });
});
