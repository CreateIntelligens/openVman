import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AsrControls } from "./AsrControls";

afterEach(() => { cleanup(); });

describe("AsrControls", () => {
  it("只有一個引擎可選時不顯示", () => {
    const { container } = render(
      <AsrControls
        provider={{ value: "", effective: "breeze", allowed: ["breeze"] }}
        onChange={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("還沒讀到設定時不顯示", () => {
    const { container } = render(<AsrControls provider={null} onChange={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it("顯示引擎的名稱而不是代號", () => {
    render(
      <AsrControls
        provider={{ value: "sensevoice", effective: "sensevoice", allowed: ["breeze", "sensevoice"] }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox", { name: "語音辨識引擎" }).textContent)
      .toContain("SenseVoice-Small");
  });

  it("選過的引擎被收回授權時，顯示實際生效的那個", () => {
    render(
      <AsrControls
        provider={{ value: "xiaomi", effective: "breeze", allowed: ["breeze", "sensevoice"] }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox", { name: "語音辨識引擎" }).textContent)
      .toContain("Breeze-ASR-26");
  });
});
