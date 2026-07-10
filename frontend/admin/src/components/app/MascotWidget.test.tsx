import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import MascotWidget from "./MascotWidget";
import { MascotProvider } from "../../context/MascotContext";

describe("MascotWidget", () => {
  beforeEach(() => {
    window.localStorage.clear();
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
});
