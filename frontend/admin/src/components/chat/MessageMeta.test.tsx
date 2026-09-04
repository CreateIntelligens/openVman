import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import MessageMeta from "./MessageMeta";
import { MESSAGE_META_EXPANDED_STORAGE_KEY } from "./messageMetaPrefs";

describe("MessageMeta", () => {
  // 這一組斷言的是展開後的內容，所以先把偏好設成展開。
  beforeEach(() => {
    window.localStorage.setItem(MESSAGE_META_EXPANDED_STORAGE_KEY, "true");
  });

  it("shows LLM call count and time next to the tool steps", () => {
    render(
      <MessageMeta
        toolSteps={[{ name: "search_knowledge", duration_s: 0.46 } as never]}
        responseTimeS={4.5}
        usage={{ calls: 3, latency_ms: 2404, by_model: { "gemini/gemini-3.5-flash-lite": { calls: 3 } } }}
      />,
    );

    expect(screen.getByText(/LLM ×3/)).not.toBeNull();
    expect(screen.getByText("gemini-3.5-flash-lite")).not.toBeNull();
    expect(screen.getByText("2.40s")).not.toBeNull();
    expect(screen.getByText("4.5s")).not.toBeNull();
  });

  it("groups tools from one round and shows the slowest duration once", () => {
    render(
      <MessageMeta
        toolSteps={[
          { name: "search_knowledge", duration_s: 1.212, round: 0, parallel: true },
          { name: "search_knowledge", duration_s: 0.7, round: 0, parallel: true },
          { name: "search_web", duration_s: 1.3, round: 1, parallel: false },
        ] as never}
      />,
    );

    expect(screen.getByText("1.212s")).not.toBeNull();
    expect(screen.queryByText("0.7s")).toBeNull();
    expect(screen.getByText("1.3s")).not.toBeNull();
  });

  it("renders nothing without tools, timing, or usage", () => {
    const { container } = render(<MessageMeta />);
    expect(container.firstChild).toBeNull();
  });

  it("lists every model with its call count when a turn fell back", () => {
    render(
      <MessageMeta
        usage={{
          calls: 2,
          latency_ms: 3000,
          by_model: {
            "gemini/gemini-3.5-flash-lite": { calls: 1 },
            "nen/gemini-3.5-flash-lite": { calls: 1 },
          },
        }}
      />,
    );

    expect(screen.getByText("gemini-3.5-flash-lite ×1 + gemini-3.5-flash-lite ×1")).not.toBeNull();
  });
});

describe("MessageMeta collapsing", () => {
  beforeEach(() => window.localStorage.setItem(MESSAGE_META_EXPANDED_STORAGE_KEY, "false"));

  it("collapses to a single chip that still shows the headline numbers", () => {
    render(
      <MessageMeta
        toolSteps={[{ name: "search_knowledge", duration_s: 1.2 }]}
        responseTimeS={3.4}
        usage={{ calls: 2 }}
      />,
    );

    // 收合時看不到工具名稱，但秒數與次數還在。
    expect(screen.queryByText("知識庫")).toBeNull();
    expect(screen.getByText(/1 個工具/)).not.toBeNull();
    expect(screen.getByText(/LLM ×2/)).not.toBeNull();
    expect(screen.getByText(/3\.4s/)).not.toBeNull();
  });

  it("expands on click and remembers the choice for the next message", () => {
    const { unmount } = render(
      <MessageMeta toolSteps={[{ name: "search_knowledge", duration_s: 1.2 }]} responseTimeS={3.4} />,
    );

    fireEvent.click(screen.getByTitle("展開處理詳情"));
    expect(screen.getByText("知識庫")).not.toBeNull();

    // 下一則訊息（重新掛載）應該直接是展開的。
    unmount();
    render(<MessageMeta toolSteps={[{ name: "search_knowledge", duration_s: 1.2 }]} responseTimeS={3.4} />);
    expect(screen.getByText("知識庫")).not.toBeNull();
  });
});
