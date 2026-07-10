import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Search from "./Search";

vi.mock("../hooks/useSemanticSearch", () => ({
  useSemanticSearch: () => ({
    canSubmit: true,
    error: "",
    loading: false,
    query: "PRP",
    response: {
      query: "PRP",
      table: "knowledge",
      results: [
        {
          text: "完全相同的 PRP 內容",
          source: "workspace",
          date: "2026-07-03",
          _score: 0.72,
          metadata: JSON.stringify({
            path: "knowledge/PRP.md",
            title: "PRP",
            heading_path: ["什麼是 PRP？"],
            chunk_id: "knowledge/PRP.md::0",
          }),
        },
      ],
    },
    setQuery: vi.fn(),
    setTable: vi.fn(),
    setTopK: vi.fn(),
    submit: vi.fn(),
    table: "knowledge",
    topK: 5,
  }),
}));

describe("Search", () => {
  it("shows hybrid result scores when an FTS hit has no vector distance", () => {
    render(<Search />);

    expect(screen.getByText("完全相同的 PRP 內容")).toBeTruthy();
    expect(screen.getByText("72.0%")).toBeTruthy();
    expect(screen.getByText("完全命中")).toBeTruthy();
    expect(screen.getByText("knowledge/PRP.md")).toBeTruthy();
  });

  it("does not render the Material Symbols fallback text for the submit icon", () => {
    render(<Search />);

    const button = screen.getByRole("button", { name: /執行查詢/ });
    expect(button.textContent).not.toMatch(/bolt/);
  });
});
