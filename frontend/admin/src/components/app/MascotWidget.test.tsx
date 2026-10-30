import { useEffect } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MascotProvider, useMascot } from "../../context/MascotContext";
import MascotWidget from "./MascotWidget";

describe("MascotWidget", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("always loads the built-in Live2D Haru, ignoring any old stored mascot choice", () => {
    // 舊版存過的 VRM／影片小助理選擇不再有意義，一律是 Haru。
    window.localStorage.setItem("avatar.mascot_id", "video-0713");
    window.localStorage.setItem("admin-mascot-open", "1");

    render(
      <MascotProvider>
        <MascotWidget />
      </MascotProvider>,
    );

    const src = decodeURIComponent(screen.getByTitle("AI 虛擬人小助理").getAttribute("src") ?? "");
    expect(src).toContain("/vendor/ai-avatar-bot/widget.html?");
    expect(src).toContain("haru_greeter_t03.model3.json");
    expect(src).toContain("fit=half");
    expect(src).not.toMatch(/engine=|vrm=|character=/);
    // 只有一個小助理，沒有切換選單。
    expect(screen.queryByText("Haru")).toBeNull();
  });

  it("starts collapsed by default so the model is not downloaded eagerly", () => {
    render(
      <MascotProvider>
        <MascotWidget />
      </MascotProvider>,
    );

    expect(screen.queryByTitle("AI 虛擬人小助理")).toBeNull();
    expect(
      screen.getByRole("button", { name: "打開 AI 虛擬人小助理" }),
    ).not.toBeNull();
  });

  it("mounts the iframe and remembers the choice once opened", () => {
    render(
      <MascotProvider>
        <MascotWidget />
      </MascotProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "打開 AI 虛擬人小助理" }));

    expect(screen.getByTitle("AI 虛擬人小助理")).not.toBeNull();
    expect(window.localStorage.getItem("admin-mascot-open")).toBe("1");
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

  it("keeps the iframe mounted but hidden after closing so reopening is instant", () => {
    window.localStorage.setItem("admin-mascot-open", "1");

    render(
      <MascotProvider>
        <MascotWidget />
      </MascotProvider>,
    );

    const frame = screen.getByTitle("AI 虛擬人小助理");
    // 關閉鍵在 widget iframe 內，透過 postMessage 通知宿主
    fireEvent(window, new MessageEvent("message", {
      data: { ns: "avatar-widget", type: "close" },
    }));

    expect(screen.getByTitle("AI 虛擬人小助理")).toBe(frame);
    expect(frame.closest(".mascot-widget")?.hasAttribute("hidden")).toBe(true);
    expect(
      screen.getByRole("button", { name: "打開 AI 虛擬人小助理" }),
    ).not.toBeNull();
  });

  it("stops all speech when the mascot is closed", () => {
    window.localStorage.setItem("admin-mascot-open", "1");
    const stopper = vi.fn();

    function SpeechConsumer() {
      const { registerSpeechStopper } = useMascot();
      useEffect(() => {
        return registerSpeechStopper(stopper);
      }, [registerSpeechStopper]);
      return null;
    }

    render(
      <MascotProvider>
        <SpeechConsumer />
        <MascotWidget />
      </MascotProvider>,
    );

    expect(stopper).not.toHaveBeenCalled();

    fireEvent(window, new MessageEvent("message", {
      data: { ns: "avatar-widget", type: "close" },
    }));

    expect(stopper).toHaveBeenCalledTimes(1);
  });
});
