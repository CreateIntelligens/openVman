import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MessageMeta from "./MessageMeta";

describe("MessageMeta", () => {
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
