import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AsrButton } from "./AsrButton";

afterEach(() => { cleanup(); });

describe("AsrButton", () => {
  it("閒置時沒有狀態文字", () => {
    render(<AsrButton supported listening={false} speaking={false} onToggle={() => {}} />);

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("button").getAttribute("aria-pressed")).toBe("false");
  });

  it("瀏覽器辨識：依有沒有偵測到人聲顯示不同提示", () => {
    const { rerender } = render(
      <AsrButton supported listening speaking={false} onToggle={() => {}} />,
    );
    expect(screen.getByRole("status").textContent).toBe("等待語音");

    rerender(<AsrButton supported listening speaking onToggle={() => {}} />);
    expect(screen.getByRole("status").textContent).toBe("聆聽中...");
  });

  it("伺服器引擎：開著就是在收音，並提示要再按一次才會送出", () => {
    // 錄音沒有「偵測到人聲」的訊號，沿用瀏覽器辨識的「等待語音」會讓人以為
    // 還沒開始收。
    render(
      <AsrButton supported listening speaking={false} engine="server" onToggle={() => {}} />,
    );

    expect(screen.getByRole("status").textContent).toBe("收音中 · 再按送出");
    expect(screen.getByRole("button").getAttribute("title")).toBe("停止並送出");
  });

  it("辨識中看得出來，而且不能再按", () => {
    const onToggle = vi.fn();
    render(
      <AsrButton
        supported
        listening={false}
        speaking={false}
        transcribing
        engine="server"
        onToggle={onToggle}
      />,
    );

    const button = screen.getByRole("button");
    expect(screen.getByRole("status").textContent).toBe("辨識中…");
    expect(button.getAttribute("aria-busy")).toBe("true");
    fireEvent.click(button);
    expect(onToggle).not.toHaveBeenCalled();
  });
});
