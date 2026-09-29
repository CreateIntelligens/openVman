import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AsrControls } from "./AsrControls";

afterEach(() => {
  cleanup();
});

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

  it("沒選過時直接顯示實際在用的引擎，不再有「預設」選項", async () => {
    render(
      <AsrControls
        provider={{ value: "", effective: "breeze", allowed: ["breeze", "sensevoice"] }}
        onChange={() => {}}
      />,
    );
    const combobox = screen.getByRole("combobox", { name: "語音辨識引擎" });
    expect(combobox.textContent).toContain("Breeze-ASR-26");
    fireEvent.click(combobox);
    const labels = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(labels).toEqual(["Breeze-ASR-26", "SenseVoice-Small"]);
  });

  it("在用的引擎沒授權給這個帳號時也列出來，選單不會一片空白", () => {
    render(
      <AsrControls
        provider={{ value: "", effective: "breeze", allowed: ["sensevoice", "xiaomi"] }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox", { name: "語音辨識引擎" }).textContent).toContain(
      "Breeze-ASR-26",
    );
  });

  it("點目前這個引擎不會送出變更", async () => {
    const onChange = vi.fn();
    render(
      <AsrControls
        provider={{ value: "", effective: "breeze", allowed: ["breeze", "sensevoice"] }}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("combobox", { name: "語音辨識引擎" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: /Breeze-ASR-26/ }));
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("combobox", { name: "語音辨識引擎" }));
    fireEvent.mouseDown(await screen.findByRole("option", { name: /SenseVoice-Small/ }));
    expect(onChange).toHaveBeenCalledWith("sensevoice");
  });

  it("顯示引擎的名稱而不是代號", () => {
    render(
      <AsrControls
        provider={{
          value: "sensevoice",
          effective: "sensevoice",
          allowed: ["breeze", "sensevoice"],
        }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox", { name: "語音辨識引擎" }).textContent).toContain(
      "SenseVoice-Small",
    );
  });

  it("選過的引擎被收回授權時，顯示實際生效的那個", () => {
    render(
      <AsrControls
        provider={{ value: "xiaomi", effective: "breeze", allowed: ["breeze", "sensevoice"] }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox", { name: "語音辨識引擎" }).textContent).toContain(
      "Breeze-ASR-26",
    );
  });
});
