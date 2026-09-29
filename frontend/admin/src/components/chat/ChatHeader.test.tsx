import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ChatHeader from "./ChatHeader";

afterEach(() => {
  cleanup();
});

const baseProps = {
  conversationTitle: "對話",
  conversationStatus: "",
  sessionId: "",
  mode: "text" as const,
  onOpenSessions: vi.fn(),
  onOpenQuickQa: vi.fn(),
};

describe("ChatHeader", () => {
  it("Live 藏起來時不顯示 Text／Live 切換", () => {
    render(<ChatHeader {...baseProps} />);
    expect(screen.queryByRole("button", { name: "Live" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Text" })).toBeNull();
  });

  it("有切換函式時顯示兩個模式", () => {
    render(<ChatHeader {...baseProps} onModeChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Live" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Text" })).toBeTruthy();
  });
});
