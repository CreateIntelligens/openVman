import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Voice from "./Tts";

vi.mock("../components/TtsPreviewPanel", () => ({
  default: () => <div>TTS 面板</div>,
}));
vi.mock("../components/AsrProviderPanel", () => ({
  default: () => <div>ASR 面板</div>,
}));

// 分頁會存進 localStorage，不清的話上一個案例選到的分頁會變成下一個的起點。
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("語音頁分頁", () => {
  it("預設顯示 TTS 試聽", () => {
    render(<Voice />);

    expect(screen.getByText("TTS 面板")).toBeTruthy();
    expect(screen.queryByText("ASR 面板")).toBeNull();
  });

  it("切到語音辨識只顯示該面板", () => {
    render(<Voice />);

    fireEvent.click(screen.getByRole("tab", { name: "語音辨識" }));

    expect(screen.getByText("ASR 面板")).toBeTruthy();
    expect(screen.queryByText("TTS 面板")).toBeNull();
  });

  it("方向鍵可在分頁之間移動", () => {
    render(<Voice />);

    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });

    expect(screen.getByRole("tab", { name: "語音辨識" }).getAttribute("aria-selected")).toBe("true");
  });

  it("只有選取中的分頁進入 Tab 鍵順序", () => {
    render(<Voice />);

    expect(screen.getByRole("tab", { name: "TTS 試聽" }).getAttribute("tabindex")).toBe("0");
    expect(screen.getByRole("tab", { name: "語音辨識" }).getAttribute("tabindex")).toBe("-1");
  });

  it("重整後回到上次的分頁", () => {
    const first = render(<Voice />);
    fireEvent.click(screen.getByRole("tab", { name: "語音辨識" }));
    first.unmount();

    render(<Voice />);

    expect(screen.getByText("ASR 面板")).toBeTruthy();
    expect(screen.queryByText("TTS 面板")).toBeNull();
  });

  it("忽略存進來的無效分頁", () => {
    window.localStorage.setItem("admin.tts.active_tab", "bogus");

    render(<Voice />);

    expect(screen.getByText("TTS 面板")).toBeTruthy();
  });
});
