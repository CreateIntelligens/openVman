import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithRedactions, RedactedPill } from "./redactedText";

describe("renderWithRedactions", () => {
  it("passes plain text through unchanged", () => {
    render(<p>{renderWithRedactions("hello world")}</p>);
    expect(screen.getByText("hello world")).not.toBeNull();
  });

  it("replaces a known category with the Chinese label", () => {
    render(<p>{renderWithRedactions("call me at [REDACTED:phone] today")}</p>);
    const pill = screen.getByTitle("已遮蔽：電話");
    expect(pill.textContent).toContain("電話");
  });

  it("falls back to 個資 for unknown categories", () => {
    render(<p>{renderWithRedactions("value: [REDACTED:weirdcat]")}</p>);
    const pill = screen.getByTitle("已遮蔽：個資");
    expect(pill.textContent).toContain("個資");
  });

  it("handles multiple redactions in one string", () => {
    render(<p>{renderWithRedactions("[REDACTED:email] and [REDACTED:phone]")}</p>);
    expect(screen.getByTitle("已遮蔽：信箱")).not.toBeNull();
    expect(screen.getByTitle("已遮蔽：電話")).not.toBeNull();
  });

  it("returns a single string when no redaction present", () => {
    const result = renderWithRedactions("no markers here");
    expect(result).toEqual(["no markers here"]);
  });
});

describe("RedactedPill", () => {
  it("renders category label with tooltip", () => {
    render(<RedactedPill category="credit_card" />);
    const pill = screen.getByTitle("已遮蔽：信用卡");
    expect(pill.textContent).toContain("信用卡");
  });
});
