import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MascotProvider } from "../../context/MascotContext";
import MascotWidget from "./MascotWidget";

describe("MascotWidget", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the selected mascot iframe source from localStorage", () => {
    window.localStorage.setItem("avatar.mascot_id", "qqman");

    render(
      <MascotProvider>
        <MascotWidget />
      </MascotProvider>,
    );

    const frame = screen.getByTitle("AI 虛擬人小助理");
    const src = frame.getAttribute("src") ?? "";

    expect(src).toContain("engine=3d");
    expect(decodeURIComponent(src)).toContain("/mascots/qqman/model.vrm");
  });

  it("starts collapsed on compact viewports", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      media: "(max-width: 48rem)",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    render(
      <MascotProvider>
        <MascotWidget />
      </MascotProvider>,
    );

    expect(
      screen.getByRole("button", { name: "打開 AI 虛擬人小助理" }),
    ).not.toBeNull();
    expect(
      screen.queryByTitle("AI 虛擬人小助理"),
    ).toBeNull();
  });
});
