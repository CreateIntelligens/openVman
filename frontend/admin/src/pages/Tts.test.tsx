import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useEffect, useState } from "react";
import { buildAdminPath, parseAdminRoute } from "../components/app/navigation";
import { NavigationProvider } from "../context/NavigationContext";
import Voice from "./Tts";

function RoutedVoice() {
  const [route, setRoute] = useState(() => parseAdminRoute(window.location.pathname, window.location.search) ?? { tab: "Tts" as const });
  useEffect(() => {
    const onPop = () => setRoute(parseAdminRoute(window.location.pathname, window.location.search) ?? { tab: "Tts" });
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return <NavigationProvider currentTab="Tts" currentSubView={route.subView} onSelectTab={(tab, subView) => {
    window.history.pushState(null, "", buildAdminPath(tab, "default", subView));
    setRoute({ tab, subView });
  }}><Voice /></NavigationProvider>;
}

vi.mock("../components/TtsPreviewPanel", () => ({
  default: () => <div>TTS 面板</div>,
}));
vi.mock("../components/AsrProviderPanel", () => ({
  default: () => <div>ASR 面板</div>,
}));

beforeEach(() => window.history.replaceState(null, "", "/admin/tts"));

// 每次從明確的網址開始，瀏覽器偏好不能覆蓋路由。
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("語音頁分頁", () => {
  it("預設顯示 TTS 試聽", () => {
    render(<RoutedVoice />);

    expect(screen.getByText("TTS 面板")).toBeTruthy();
    expect(screen.queryByText("ASR 面板")).toBeNull();
  });

  it("切到語音辨識只顯示該面板", () => {
    render(<RoutedVoice />);

    fireEvent.click(screen.getByRole("tab", { name: "語音辨識" }));

    expect(screen.getByText("ASR 面板")).toBeTruthy();
    expect(window.location.pathname).toBe("/admin/tts/asr");
    expect(screen.queryByText("TTS 面板")).toBeNull();
  });

  it("方向鍵可在分頁之間移動", () => {
    render(<RoutedVoice />);

    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });

    expect(screen.getByRole("tab", { name: "語音辨識" }).getAttribute("aria-selected")).toBe("true");
  });

  it("只有選取中的分頁進入 Tab 鍵順序", () => {
    render(<RoutedVoice />);

    expect(screen.getByRole("tab", { name: "TTS 試聽" }).getAttribute("tabindex")).toBe("0");
    expect(screen.getByRole("tab", { name: "語音辨識" }).getAttribute("tabindex")).toBe("-1");
  });

  it("重新掛載依網址開啟 ASR 分頁", () => {
    const first = render(<RoutedVoice />);
    fireEvent.click(screen.getByRole("tab", { name: "語音辨識" }));
    first.unmount();

    render(<RoutedVoice />);

    expect(screen.getByText("ASR 面板")).toBeTruthy();
    expect(screen.queryByText("TTS 面板")).toBeNull();
  });

  it("明確 TTS 路由優先於保存的 ASR 偏好", () => {
    window.localStorage.setItem("admin.tts.active_tab", "asr");

    render(<RoutedVoice />);

    expect(screen.getByText("TTS 面板")).toBeTruthy();
  });
  it("直接開啟 ASR 路徑並隨 history 回到 TTS", () => {
    window.history.replaceState(null, "", "/admin/tts/asr");
    render(<RoutedVoice />);
    expect(screen.getByText("ASR 面板")).toBeTruthy();
    window.history.pushState(null, "", "/admin/tts");
    fireEvent.popState(window);
    expect(screen.getByText("TTS 面板")).toBeTruthy();
  });

});
