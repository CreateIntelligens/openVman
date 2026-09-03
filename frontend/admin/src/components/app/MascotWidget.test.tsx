import { useEffect } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchAvatarMascotsMock = vi.hoisted(() => vi.fn());
vi.mock("../../api/avatar", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/avatar")>()),
  fetchAvatarMascots: fetchAvatarMascotsMock,
}));

import { MascotProvider, useMascot } from "../../context/MascotContext";
import MascotWidget from "./MascotWidget";

describe("MascotWidget", () => {
  beforeEach(() => {
    window.localStorage.clear();
    fetchAvatarMascotsMock.mockReset();
    fetchAvatarMascotsMock.mockRejectedValue(new Error("offline"));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the selected mascot iframe source from localStorage", () => {
    window.localStorage.setItem("avatar.mascot_id", "qqman");
    // VRM 最大可到 20MB，widget 預設收合；展開過才會掛 iframe。
    window.localStorage.setItem("admin-mascot-open", "1");

    render(
      <MascotProvider>
        <MascotWidget />
      </MascotProvider>,
    );

    const frame = screen.getByTitle("AI 虛擬人小助理");
    const src = frame.getAttribute("src") ?? "";

    expect(src).toContain("engine=3d");
    expect(decodeURIComponent(src)).toContain("/static/mascots/qqman/model.vrm");
  });

  it("starts collapsed by default so the VRM is not downloaded eagerly", () => {
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

  it("builds a video mascot source from the character id", () => {
    window.localStorage.setItem("admin-mascot-open", "1");
    window.localStorage.setItem("avatar.mascot_id", "matex-000");

    render(
      <MascotProvider initialOptions={[
        { id: "matex-000", label: "Matex", engine: "video", characterId: "000" },
      ]}>
        <MascotWidget />
      </MascotProvider>,
    );

    const src = screen.getByTitle("AI 虛擬人小助理").getAttribute("src") ?? "";
    expect(src).toContain("engine=video");
    expect(src).toContain("character=000");
  });

  it("loads the backend mascot list on mount so derived video characters appear everywhere", async () => {
    window.localStorage.setItem("admin-mascot-open", "1");
    window.localStorage.setItem("avatar.mascot_id", "video-000");
    fetchAvatarMascotsMock.mockResolvedValue({
      mascots: [
        {
          mascot_id: "video-000",
          label: "預設角色",
          engine: "video",
          model_url: "",
          vrm_url: "",
          character_id: "000",
          thumbnail_url: "",
          fit: "",
          builtin: true,
        },
      ],
    });

    render(
      <MascotProvider>
        <MascotWidget />
      </MascotProvider>,
    );

    await waitFor(() => {
      const src = screen.getByTitle("AI 虛擬人小助理").getAttribute("src") ?? "";
      expect(src).toContain("character=000");
    });
    expect(screen.getByText("預設角色")).not.toBeNull();
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
